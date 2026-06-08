"""
AILA Course Builder — Increment 2 (second half) test

Does BOTH writes for one course, with strong guardrails:
  A) Attaches the notes .txt to the agent's Knowledge Base.
  B) Inserts the course line into the System prompt's COURSE MENU,
     in alphabetical order, touching nothing else.

Guardrails:
  - If the COURSE MENU heading can't be found, the prompt is left UNCHANGED.
  - If the course is already in the KB or the menu, that part is skipped.
  - Everything other than the one KB list item and the one menu line is
    sent back exactly as it was.
  - Agents are versioned, so a bad change can be rolled back.

How to test in a browser:
  https://aila-course-files.vercel.app/api/test_attach_and_menu
  (optional: ?txt=Some-File.txt   ?agent_id=...)

Returns JSON describing what happened to each of the two areas.
"""

import os
import json
import uuid
import urllib.parse
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler

DEFAULT_AGENT_ID = 'agent_2201kthka4h3fddvtxj1sz9q4be8'   # recommender (Learning Path Creator)
DEFAULT_TXT = 'Advanced-Prompt-Engineering-for-High-Performing-Professionals.txt'

TEST_REPO_RAW = 'https://raw.githubusercontent.com/jdidonatojr/aila-course-files-test/main/'
EL_AGENT_URL = 'https://api.elevenlabs.io/v1/convai/agents/'
EL_KB_FILE_URL = 'https://api.elevenlabs.io/v1/convai/knowledge-base/file'


def fetch_txt(filename):
    url = TEST_REPO_RAW + urllib.parse.quote(filename)
    with urllib.request.urlopen(urllib.request.Request(url), timeout=60) as resp:
        return resp.read()


def el_get_agent(key, agent_id):
    url = EL_AGENT_URL + urllib.parse.quote(agent_id)
    req = urllib.request.Request(url, method='GET')
    req.add_header('xi-api-key', key)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode('utf-8'))


def el_create_doc_from_file(key, filename, file_bytes):
    boundary = '----ailaBoundary' + uuid.uuid4().hex
    nl = b'\r\n'
    parts = [
        ('--' + boundary).encode(),
        ('Content-Disposition: form-data; name="file"; filename="%s"' % filename).encode(),
        b'Content-Type: text/plain', b'', file_bytes,
        ('--' + boundary).encode(),
        b'Content-Disposition: form-data; name="name"', b'', filename.encode(),
        ('--' + boundary + '--').encode(), b'',
    ]
    body = nl.join(parts)
    req = urllib.request.Request(EL_KB_FILE_URL, data=body, method='POST')
    req.add_header('xi-api-key', key)
    req.add_header('Content-Type', 'multipart/form-data; boundary=' + boundary)
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode('utf-8')).get('id')


def el_patch_agent(key, agent_id, conversation_config):
    url = EL_AGENT_URL + urllib.parse.quote(agent_id)
    body = json.dumps({'conversation_config': conversation_config}).encode('utf-8')
    req = urllib.request.Request(url, data=body, method='PATCH')
    req.add_header('xi-api-key', key)
    req.add_header('Content-Type', 'application/json')
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode('utf-8'))


def insert_into_menu(prompt_text, new_line):
    """
    Insert '- Name.txt' into the '# COURSE MENU' section alphabetically.
    Works whether the prompt has real line breaks OR is one long run.
    Returns (new_prompt, status).
    """
    new_name = new_line.strip()[2:].strip()
    lower_new = new_name.lower()

    # ----- Case 1: the prompt has real line breaks -----
    if '\n' in prompt_text:
        lines = prompt_text.split('\n')
        start = next((i for i, ln in enumerate(lines)
                      if ln.strip().startswith('# COURSE MENU')), None)
        if start is None:
            return prompt_text, 'menu_not_found'
        end = len(lines)
        for j in range(start + 1, len(lines)):
            if lines[j].strip().startswith('#'):
                end = j
                break
        item_idxs = [k for k in range(start + 1, end) if lines[k].strip().startswith('- ')]
        for k in item_idxs:
            if lines[k].strip()[2:].strip().lower() == lower_new:
                return prompt_text, 'already_in_menu'
        insert_at = None
        for k in item_idxs:
            if lower_new < lines[k].strip()[2:].strip().lower():
                insert_at = k
                break
        if insert_at is None:
            insert_at = (item_idxs[-1] + 1) if item_idxs else (start + 1)
        lines.insert(insert_at, new_line)
        return '\n'.join(lines), 'inserted'

    # ----- Case 2: the prompt is one long run (items separated by ' - ') -----
    if '# COURSE MENU' not in prompt_text:
        return prompt_text, 'menu_not_found'
    if (new_name.lower()) in prompt_text.lower():
        return prompt_text, 'already_in_menu'
    marker = '# COURSE MENU'
    idx = prompt_text.find(marker)
    first_item = prompt_text.find(' - ', idx)
    if first_item == -1:
        return prompt_text, 'menu_not_found'
    new_prompt = prompt_text[:first_item] + ' - ' + new_name + prompt_text[first_item:]
    return new_prompt, 'inserted_unsorted'


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            key = os.environ.get('ELEVENLABS_API_KEY', '').strip()
            if not key:
                return self._send(500, {'ok': False,
                    'message': 'ELEVENLABS_API_KEY is not set on this project.'})

            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            txt_name = q.get('txt', [DEFAULT_TXT])[0].strip()
            agent_id = q.get('agent_id', [DEFAULT_AGENT_ID])[0].strip()
            menu_line = '- ' + txt_name

            agent = el_get_agent(key, agent_id)
            cc = agent.get('conversation_config', {})
            prompt_obj = cc.get('agent', {}).get('prompt', {})
            kb_list = prompt_obj.get('knowledge_base', [])
            if not isinstance(kb_list, list):
                kb_list = []
            prompt_text = prompt_obj.get('prompt', '')

            # ---------- PART A: Knowledge Base ----------
            already_kb = any(isinstance(it, dict) and it.get('name') == txt_name
                             for it in kb_list)
            if already_kb:
                kb_status = 'already_attached'
            else:
                file_bytes = fetch_txt(txt_name)
                if len(file_bytes) < 20:
                    return self._send(404, {'ok': False,
                        'message': f'{txt_name} not found (or empty) in the test repo.'})
                doc_id = el_create_doc_from_file(key, txt_name, file_bytes)
                if not doc_id:
                    return self._send(502, {'ok': False,
                        'message': 'ElevenLabs did not return a document id.'})
                kb_list.append({'type': 'file', 'name': txt_name,
                                'id': doc_id, 'usage_mode': 'auto'})
                kb_status = 'attached'

            # ---------- PART B: System prompt COURSE MENU ----------
            new_prompt_text, menu_status = insert_into_menu(prompt_text, menu_line)

            # ---------- Write back only what changed ----------
            prompt_obj['knowledge_base'] = kb_list
            prompt_obj['prompt'] = new_prompt_text
            cc['agent']['prompt'] = prompt_obj
            el_patch_agent(key, agent_id, cc)

            return self._send(200, {
                'ok': True,
                'course': txt_name,
                'knowledge_base_result': kb_status,
                'menu_result': menu_status,
                'kb_count_after': len(kb_list),
                'note': ('menu_not_found means the prompt was left unchanged for the menu; '
                         'inserted_unsorted means your prompt is one long run, so it was '
                         'added but not alphabetically placed.'),
                'message': 'Done. Now check the dashboard for a Publish prompt, and verify the prompt text looks right.'
            })

        except urllib.error.HTTPError as e:
            detail = ''
            try:
                detail = e.read().decode('utf-8', errors='replace')[:400]
            except Exception:
                pass
            return self._send(502, {'ok': False,
                'message': f'ElevenLabs API error ({e.code}): {detail}'})
        except Exception as e:
            return self._send(500, {'ok': False, 'message': f'Server error: {str(e)}'})

    def _send(self, code, obj):
        body = json.dumps(obj, indent=2, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
