"""
AILA Course Builder — Increment 3, sub-step 3.2  (STANDALONE CHAIN TEST)

Chains the proven steps into ONE call, with a stop-at-first-failure checklist:
  1. PDF present in the test repo  (push from CloudConvert if ?job_id= given,
     otherwise just verify the PDF is already there)
  2. courses.json — real course entry (smallest-unused number; replaces a
     leftover TEST placeholder if present)
  3. Knowledge base — upload the notes .txt and attach to the recommender agent
  4. Course menu — insert the course into the agent's System prompt COURSE MENU
  5. Live link — build the test URL from the player base

Every step is re-run safe (create-or-update / skip-if-present), so after a
failure you fix the cause and just run it again — finished steps skip.

Defaults are preloaded for the "Practicing Difficult Conversations with AI"
course, so you can just open the URL. Override with query params if needed:
  ?job_id=...  ?title=...  ?pdf=...  ?txt=...  ?total_slides=NN
  ?sections=A~B~C  ?player_base=https://host/subfolder/  ?agent_id=...

How to test:
  https://aila-course-files.vercel.app/api/test_publish_course
"""

import os
import re
import json
import uuid
import base64
import urllib.parse
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler

OWNER = 'jdidonatojr'
REPO = 'aila-course-files-test'
BRANCH = 'main'
COURSES_PATH = 'courses.json'
API_ROOT = 'https://api.github.com'
RAW_ROOT = f'https://raw.githubusercontent.com/{OWNER}/{REPO}/{BRANCH}/'
CC_SYNC_ROOT = 'https://sync.api.cloudconvert.com/v2/jobs/'
EL_AGENT_URL = 'https://api.elevenlabs.io/v1/convai/agents/'
EL_KB_FILE_URL = 'https://api.elevenlabs.io/v1/convai/knowledge-base/file'

# ---- Preloaded defaults (Practicing course) ----
DEFAULT_TITLE = 'Practicing Difficult Conversations with AI'
DEFAULT_PDF = 'Practicing-Difficult-Conversations-with-AI.pdf'
DEFAULT_TXT = 'Practicing-Difficult-Conversations-with-AI.txt'
DEFAULT_TOTAL_SLIDES = 12
DEFAULT_SECTIONS = [
    'Opening and Welcome (slides 1-2)',
    'Why Difficult Conversations Matter (3-5)',
    'The Role-Play Method (6-8)',
    'Practicing with AI (9-11)',
    'Recap and Next Steps (12)',
]
DEFAULT_PLAYER_BASE = 'https://ailearningalliance.org/teacher-we/'
DEFAULT_AGENT_ID = 'agent_2201kthka4h3fddvtxj1sz9q4be8'


# ---------- small helpers ----------
def gh_headers(token):
    return {'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'aila-course-builder',
            'Content-Type': 'application/json'}


def slugify(text):
    return re.sub(r'[^a-zA-Z0-9]+', '_', text).strip('_').lower()


def parse_sections(lines):
    sections, problems = [], []
    for raw in lines:
        label = raw.strip()
        if not label:
            continue
        groups = re.findall(r'\(([^)]*)\)', label)
        start = None
        if groups:
            m = re.search(r'\d+', groups[-1])
            if m:
                start = int(m.group())
        if start is None:
            problems.append(label)
            continue
        sections.append({'label': label, 'startSlide': start})
    return sections, problems


def http_get_bytes(url, headers=None, timeout=120):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def insert_into_menu(prompt_text, new_line):
    new_name = new_line.strip()[2:].strip()
    lower_new = new_name.lower()
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
    if '# COURSE MENU' not in prompt_text:
        return prompt_text, 'menu_not_found'
    if new_name.lower() in prompt_text.lower():
        return prompt_text, 'already_in_menu'
    idx = prompt_text.find('# COURSE MENU')
    first_item = prompt_text.find(' - ', idx)
    if first_item == -1:
        return prompt_text, 'menu_not_found'
    return prompt_text[:first_item] + ' - ' + new_name + prompt_text[first_item:], 'inserted_unsorted'


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        steps = []

        def record(name, status, detail=''):
            steps.append({'step': name, 'status': status, 'detail': detail})

        try:
            token = os.environ.get('GITHUB_TOKEN', '').strip()
            el_key = os.environ.get('ELEVENLABS_API_KEY', '').strip()

            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            title = q.get('title', [DEFAULT_TITLE])[0].strip()
            pdf = q.get('pdf', [DEFAULT_PDF])[0].strip()
            txt = q.get('txt', [DEFAULT_TXT])[0].strip()
            total_slides = int(q.get('total_slides', [str(DEFAULT_TOTAL_SLIDES)])[0])
            section_lines = q['sections'][0].split('~') if 'sections' in q else DEFAULT_SECTIONS
            player_base = q.get('player_base', [DEFAULT_PLAYER_BASE])[0].strip()
            agent_id = q.get('agent_id', [DEFAULT_AGENT_ID])[0].strip()
            job_id = q.get('job_id', [''])[0].strip()

            course_id = slugify(title)
            pdf_url = RAW_ROOT + pdf

            if not token:
                record('setup', 'failed', 'GITHUB_TOKEN not set')
                return self._finish(False, steps, None)
            if not el_key:
                record('setup', 'failed', 'ELEVENLABS_API_KEY not set')
                return self._finish(False, steps, None)

            # ---------- STEP 1: PDF in repo ----------
            try:
                if job_id:
                    cc_key = os.environ.get('CLOUDCONVERT_API_KEY', '').strip()
                    info = json.loads(http_get_bytes(
                        CC_SYNC_ROOT + urllib.parse.quote(job_id),
                        {'Authorization': 'Bearer ' + cc_key}).decode('utf-8'))
                    tasks = info.get('data', {}).get('tasks', [])
                    src_url = None
                    for t in tasks:
                        if t.get('name') == 'export-pdf' and t.get('status') == 'finished':
                            files = (t.get('result') or {}).get('files') or []
                            if files:
                                src_url = files[0].get('url')
                                pdf = files[0].get('filename')
                                pdf_url = RAW_ROOT + pdf
                            break
                    if not src_url:
                        raise RuntimeError('No finished PDF found for that job_id.')
                    raw = http_get_bytes(src_url)
                    sha = None
                    try:
                        meta = json.loads(http_get_bytes(
                            f'{API_ROOT}/repos/{OWNER}/{REPO}/contents/{urllib.parse.quote(pdf)}?ref={BRANCH}',
                            gh_headers(token), 30).decode('utf-8'))
                        sha = meta.get('sha')
                    except urllib.error.HTTPError as e:
                        if e.code != 404:
                            raise
                    body = {'message': f'Add course PDF: {pdf}',
                            'content': base64.b64encode(raw).decode('ascii'), 'branch': BRANCH}
                    if sha:
                        body['sha'] = sha
                    req = urllib.request.Request(
                        f'{API_ROOT}/repos/{OWNER}/{REPO}/contents/{urllib.parse.quote(pdf)}',
                        data=json.dumps(body).encode('utf-8'),
                        headers=gh_headers(token), method='PUT')
                    urllib.request.urlopen(req, timeout=60).read()
                    record('1_pdf', 'pushed', f'{pdf} ({len(raw)} bytes)')
                else:
                    raw = http_get_bytes(pdf_url, timeout=30)
                    if len(raw) < 1000:
                        raise RuntimeError(f'{pdf} not found in repo (provide ?job_id= to push it).')
                    record('1_pdf', 'present', f'{pdf} ({len(raw)} bytes)')
            except Exception as e:
                record('1_pdf', 'failed', str(e))
                return self._finish(False, steps, None)

            # ---------- STEP 2: courses.json ----------
            try:
                sections, problems = parse_sections(section_lines)
                if problems:
                    raise RuntimeError('Section lines missing a slide number: ' + '; '.join(problems))
                meta = json.loads(http_get_bytes(
                    f'{API_ROOT}/repos/{OWNER}/{REPO}/contents/{COURSES_PATH}?ref={BRANCH}',
                    gh_headers(token), 30).decode('utf-8'))
                data = json.loads(base64.b64decode(meta['content']).decode('utf-8'))
                csha = meta['sha']
                entry = {'id': course_id, 'title': title, 'totalSlides': total_slides,
                         'pdfUrl': pdf_url,
                         'firstMessage': f'Welcome to {title}. Are you ready to begin?',
                         'sections': sections}
                existing_key, is_ph = None, False
                for k, v in data.items():
                    if isinstance(v, dict) and v.get('pdfUrl') == pdf_url:
                        existing_key = k
                        tv = str(v.get('title', ''))
                        is_ph = tv.startswith('TEST —') or tv.startswith('TEST -')
                        break
                if existing_key is not None and not is_ph:
                    course_number = existing_key
                    cj_status = 'updated_in_place'
                else:
                    if existing_key is not None and is_ph:
                        del data[existing_key]
                    used = set(int(k) for k in data.keys() if str(k).isdigit())
                    n = 1
                    while n in used:
                        n += 1
                    course_number = str(n)
                    cj_status = 'created'
                data[course_number] = entry
                text = json.dumps(data, indent=2, ensure_ascii=False) + '\n'
                body = {'message': 'Update courses.json (3.2 chain)',
                        'content': base64.b64encode(text.encode('utf-8')).decode('ascii'),
                        'branch': BRANCH, 'sha': csha}
                req = urllib.request.Request(
                    f'{API_ROOT}/repos/{OWNER}/{REPO}/contents/{COURSES_PATH}',
                    data=json.dumps(body).encode('utf-8'),
                    headers=gh_headers(token), method='PUT')
                urllib.request.urlopen(req, timeout=30).read()
                record('2_courses_json', cj_status, f'course #{course_number}')
            except Exception as e:
                record('2_courses_json', 'failed', str(e))
                return self._finish(False, steps, None)

            # ---------- STEP 3 & 4: agent KB + menu (one read, one save) ----------
            try:
                agent = json.loads(http_get_bytes(
                    EL_AGENT_URL + urllib.parse.quote(agent_id),
                    {'xi-api-key': el_key}, 60).decode('utf-8'))
                cc = agent.get('conversation_config', {})
                prompt_obj = cc.get('agent', {}).get('prompt', {})
                kb_list = prompt_obj.get('knowledge_base', [])
                if not isinstance(kb_list, list):
                    kb_list = []
                prompt_text = prompt_obj.get('prompt', '')
                changed = False

                if any(isinstance(it, dict) and it.get('name') == txt for it in kb_list):
                    kb_status = 'already_attached'
                else:
                    file_bytes = http_get_bytes(RAW_ROOT + urllib.parse.quote(txt), timeout=60)
                    if len(file_bytes) < 20:
                        raise RuntimeError(f'{txt} not found (or empty) in repo.')
                    boundary = '----ailaBoundary' + uuid.uuid4().hex
                    nl = b'\r\n'
                    parts = [('--' + boundary).encode(),
                             ('Content-Disposition: form-data; name="file"; filename="%s"' % txt).encode(),
                             b'Content-Type: text/plain', b'', file_bytes,
                             ('--' + boundary).encode(),
                             b'Content-Disposition: form-data; name="name"', b'', txt.encode(),
                             ('--' + boundary + '--').encode(), b'']
                    req = urllib.request.Request(EL_KB_FILE_URL, data=nl.join(parts), method='POST')
                    req.add_header('xi-api-key', el_key)
                    req.add_header('Content-Type', 'multipart/form-data; boundary=' + boundary)
                    doc = json.loads(urllib.request.urlopen(req, timeout=120).read().decode('utf-8'))
                    kb_list.append({'type': 'file', 'name': txt, 'id': doc.get('id'), 'usage_mode': 'auto'})
                    kb_status = 'attached'
                    changed = True

                new_prompt, menu_status = insert_into_menu(prompt_text, '- ' + txt)
                if menu_status in ('inserted', 'inserted_unsorted'):
                    changed = True

                if changed:
                    prompt_obj['knowledge_base'] = kb_list
                    prompt_obj['prompt'] = new_prompt
                    cc['agent']['prompt'] = prompt_obj
                    pbody = json.dumps({'conversation_config': cc}).encode('utf-8')
                    preq = urllib.request.Request(EL_AGENT_URL + urllib.parse.quote(agent_id),
                                                  data=pbody, method='PATCH')
                    preq.add_header('xi-api-key', el_key)
                    preq.add_header('Content-Type', 'application/json')
                    urllib.request.urlopen(preq, timeout=120).read()

                record('3_knowledge_base', kb_status, '')
                record('4_course_menu', menu_status, '')
            except Exception as e:
                record('3_4_agent', 'failed', str(e))
                return self._finish(False, steps, None)

            # ---------- STEP 5: live link ----------
            live_url = player_base.rstrip('/') + '/?course=' + course_number
            record('5_live_link', 'built', live_url)

            return self._finish(True, steps, live_url)

        except Exception as e:
            record('unexpected', 'failed', str(e))
            return self._finish(False, steps, None)

    def _finish(self, ok, steps, live_url):
        payload = {
            'ok': ok,
            'summary': ('✅ Course is live.' if ok else '⚠️ Stopped at a failed step — fix it and run again.'),
            'checklist': steps,
        }
        if ok and live_url:
            payload['test_link'] = live_url
            payload['message'] = 'Course is live. Test it here: ' + live_url
        return self._send(200 if ok else 502, payload)

    def _send(self, code, obj):
        body = json.dumps(obj, indent=2, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
