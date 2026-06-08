"""
AILA Course Builder — Increment 2 WRITE test (sandbox agent)

What it does:
  1. Fetches a notes .txt from the TEST content repo.
  2. Uploads it to ElevenLabs as a knowledge-base document,
     named with the EXACT .txt filename.
  3. Reads the recommender agent's full conversation_config.
  4. Appends the new document to the knowledge-base list, leaving
     EVERYTHING ELSE (especially the system prompt) untouched.
  5. Saves it back.

Safety:
  - If a document with the same name is already attached, it STOPS and
    reports "already attached" — so re-running can't create duplicates.
  - It sends the whole conversation_config back unchanged except for the
    one added list item, so nothing else can be lost.
  - Agents are versioned, so a bad change can be rolled back in the dashboard.

How to test in a browser:
  https://aila-course-files.vercel.app/api/test_attach_notes
  (optional: ?txt=Some-File.txt   ?agent_id=...)

Returns JSON: { ok, action, document_id, document_name, count_before, count_after, message }
"""

import os
import json
import uuid
import urllib.parse
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler

# Defaults for this test
DEFAULT_AGENT_ID = 'agent_2201kthka4h3fddvtxj1sz9q4be8'   # recommender (Learning Path Creator)
DEFAULT_TXT = 'Practicing-Difficult-Conversations-with-AI.txt'

TEST_REPO_RAW = 'https://raw.githubusercontent.com/jdidonatojr/aila-course-files-test/main/'
EL_AGENT_URL = 'https://api.elevenlabs.io/v1/convai/agents/'
EL_KB_FILE_URL = 'https://api.elevenlabs.io/v1/convai/knowledge-base/file'


def fetch_txt(filename):
    """Download the notes .txt from the test repo. Returns raw bytes."""
    url = TEST_REPO_RAW + urllib.parse.quote(filename)
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def el_get_agent(key, agent_id):
    url = EL_AGENT_URL + urllib.parse.quote(agent_id)
    req = urllib.request.Request(url, method='GET')
    req.add_header('xi-api-key', key)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode('utf-8'))


def el_create_doc_from_file(key, filename, file_bytes):
    """
    Upload a file to create a knowledge-base document.
    Builds a multipart/form-data body by hand (no extra libraries).
    Returns the new document's id.
    """
    boundary = '----ailaBoundary' + uuid.uuid4().hex
    nl = b'\r\n'
    parts = []

    # The file itself (field name: "file")
    parts.append(('--' + boundary).encode())
    parts.append(
        ('Content-Disposition: form-data; name="file"; filename="%s"' % filename).encode()
    )
    parts.append(b'Content-Type: text/plain')
    parts.append(b'')
    parts.append(file_bytes)

    # The human-readable name (field name: "name")
    parts.append(('--' + boundary).encode())
    parts.append(b'Content-Disposition: form-data; name="name"')
    parts.append(b'')
    parts.append(filename.encode())

    # Closing boundary
    parts.append(('--' + boundary + '--').encode())
    parts.append(b'')

    body = nl.join(parts)

    req = urllib.request.Request(EL_KB_FILE_URL, data=body, method='POST')
    req.add_header('xi-api-key', key)
    req.add_header('Content-Type', 'multipart/form-data; boundary=' + boundary)
    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read().decode('utf-8'))
    return result.get('id'), result


def el_patch_agent(key, agent_id, conversation_config):
    """Send the (modified) conversation_config back to the agent."""
    url = EL_AGENT_URL + urllib.parse.quote(agent_id)
    body = json.dumps({'conversation_config': conversation_config}).encode('utf-8')
    req = urllib.request.Request(url, data=body, method='PATCH')
    req.add_header('xi-api-key', key)
    req.add_header('Content-Type', 'application/json')
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode('utf-8'))


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            key = os.environ.get('ELEVENLABS_API_KEY', '').strip()
            if not key:
                return self._send(500, {'ok': False,
                    'message': 'ELEVENLABS_API_KEY is not set on this project.'})

            query = urllib.parse.urlparse(self.path).query
            params = urllib.parse.parse_qs(query)
            txt_name = params.get('txt', [DEFAULT_TXT])[0].strip()
            agent_id = params.get('agent_id', [DEFAULT_AGENT_ID])[0].strip()

            # 1. Read the current agent config.
            agent = el_get_agent(key, agent_id)
            cc = agent.get('conversation_config', {})
            prompt = cc.get('agent', {}).get('prompt', {})
            kb_list = prompt.get('knowledge_base', [])
            if not isinstance(kb_list, list):
                kb_list = []
            count_before = len(kb_list)

            # 2. Safety: if this name is already attached, stop here.
            for item in kb_list:
                if isinstance(item, dict) and item.get('name') == txt_name:
                    return self._send(200, {
                        'ok': True,
                        'action': 'already_attached',
                        'document_name': txt_name,
                        'count_before': count_before,
                        'count_after': count_before,
                        'message': 'A document with this name is already attached. Nothing changed.'
                    })

            # 3. Fetch the .txt from the repo.
            file_bytes = fetch_txt(txt_name)
            if len(file_bytes) < 20:
                return self._send(404, {'ok': False,
                    'message': f'The file {txt_name} was not found (or is empty) in the test repo.'})

            # 4. Create the knowledge-base document.
            doc_id, _raw = el_create_doc_from_file(key, txt_name, file_bytes)
            if not doc_id:
                return self._send(502, {'ok': False,
                    'message': 'ElevenLabs did not return a document id.'})

            # 5. Append the new document to the list (defensive: only this changes).
            kb_list.append({
                'type': 'file',
                'name': txt_name,
                'id': doc_id,
                'usage_mode': 'auto',
            })
            prompt['knowledge_base'] = kb_list
            cc['agent']['prompt'] = prompt

            # 6. Send the whole conversation_config back, unchanged except the list.
            el_patch_agent(key, agent_id, cc)

            return self._send(200, {
                'ok': True,
                'action': 'attached',
                'document_id': doc_id,
                'document_name': txt_name,
                'count_before': count_before,
                'count_after': count_before + 1,
                'message': 'Uploaded and attached. Check the dashboard to see if a Publish step is needed.'
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
            return self._send(500, {'ok': False,
                'message': f'Server error: {str(e)}'})

    def _send(self, code, obj):
        body = json.dumps(obj, indent=2, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
