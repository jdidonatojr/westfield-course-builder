"""
AILA Course Builder — Builder B backend:  /api/publish_course   (POST)

Publishes a course end to end. Returns a stop-at-first-failure checklist
and a live link.

Expected JSON body:
  {
    "job_id":        "<CloudConvert job id>",
    "pdf_filename":  "Course-Name.pdf",
    "txt_filename":  "Course-Name.txt",
    "txt_content":   "<full instructor notes>",
    "course_title":  "Course Name",
    "course_type":   "Skills-based, hands-on",
    "audience":      "Sales reps ...",
    "section_map":   "Intro (slides 1-3)\n...",     # one per line
    "teaching_notes":"- bullet\n- bullet ...",       # one per line
    "total_slides":  12,
    "player_base":   "https://host/subfolder/",
    "agent_id":      "agent_..."   # optional recommender override
  }

Steps (each re-run safe):
  1. PDF  -> CloudConvert -> repo (under pdf_filename)
  2. courses.json -> entry, smallest-unused number (clears TEST placeholder)
  3. RECOMMENDER agent -> attach notes (.txt) + add to its COURSE MENU
  4. TEACHER agent -> attach PDF + TXT  AND  insert a COURSE LIBRARY profile block
  5. Live link
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
REPO = 'westfield-course-files'
BRANCH = 'main'
COURSES_PATH = 'courses.json'
API_ROOT = 'https://api.github.com'
RAW_ROOT = f'https://raw.githubusercontent.com/{OWNER}/{REPO}/{BRANCH}/'
CC_SYNC_ROOT = 'https://sync.api.cloudconvert.com/v2/jobs/'
EL_AGENT_URL = 'https://api.elevenlabs.io/v1/convai/agents/'
EL_KB_FILE_URL = 'https://api.elevenlabs.io/v1/convai/knowledge-base/file'

RECOMMENDER_AGENT_ID = 'agent_2201kthka4h3fddvtxj1sz9q4be8'   # Learning Path Creator
TEACHER_AGENT_ID = 'agent_5701kth9zyb9e90rcm2w0rrc5f8n'       # Teacher of the Future


def resolve_tenant(tenant_name):
    """Return the connection card for the chosen tenant.

    If a tenant name is given, it MUST exist in TENANTS_JSON (no silent
    fallback, so a typo can never publish into the wrong place).
    If no tenant name is given, fall back to the original hardcoded
    values so existing behavior is unchanged.
    """
    fallback = {
        'label': 'Default (built-in)',
        'elevenlabs_api_key': os.environ.get('ELEVENLABS_API_KEY', '').strip(),
        'teacher_agent_id': TEACHER_AGENT_ID,
        'recommender_agent_id': RECOMMENDER_AGENT_ID,
        'github_token': os.environ.get('GITHUB_TOKEN', '').strip(),
        'github_owner': OWNER,
        'github_repo': REPO,
        'player_base': '',
    }
    if not tenant_name:
        return fallback, None

    raw = os.environ.get('TENANTS_JSON', '').strip()
    if not raw:
        return None, 'Tenant "%s" was chosen but TENANTS_JSON is not set.' % tenant_name
    try:
        tenants = json.loads(raw)
    except Exception:
        return None, 'TENANTS_JSON is not valid JSON. Fix the Vercel setting.'
    card = tenants.get(tenant_name)
    if not isinstance(card, dict):
        return None, 'Tenant "%s" was not found in TENANTS_JSON.' % tenant_name

    # A named tenant's card must be COMPLETE on its own. We never backfill
    # from the built-in defaults, so an incomplete card can never silently
    # publish into another tenant's agents or repo.
    merged = {k: str(v).strip() for k, v in card.items() if v is not None}
    merged.setdefault('label', tenant_name)
    merged.setdefault('player_base', '')
    required = ['elevenlabs_api_key', 'teacher_agent_id', 'recommender_agent_id',
                'github_token', 'github_owner', 'github_repo']
    missing = [k for k in required if not merged.get(k)]
    if missing:
        return None, 'Tenant "%s" card is missing: %s' % (tenant_name, ', '.join(missing))
    return merged, None

DIVIDER = '# -----------------------------------------------------'


def gh_headers(token):
    return {'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'aila-course-builder',
            'Content-Type': 'application/json'}


def slugify(text):
    return re.sub(r'[^a-zA-Z0-9]+', '_', text).strip('_').lower()


def clean_lines(text):
    """Split into trimmed lines, dropping blanks and any leading '- ' bullet."""
    out = []
    for raw in (text or '').splitlines():
        s = raw.strip()
        if not s:
            continue
        if s.startswith('- '):
            s = s[2:].strip()
        if s:
            out.append(s)
    return out


def parse_sections(text):
    sections, problems = [], []
    for label in clean_lines(text):
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


def el_get_agent(el_key, agent_id):
    return json.loads(http_get_bytes(
        EL_AGENT_URL + urllib.parse.quote(agent_id), {'xi-api-key': el_key}, 60).decode('utf-8'))


def el_create_doc(el_key, name, file_bytes, content_type):
    boundary = '----ailaBoundary' + uuid.uuid4().hex
    nl = b'\r\n'
    parts = [('--' + boundary).encode(),
             ('Content-Disposition: form-data; name="file"; filename="%s"' % name).encode(),
             ('Content-Type: ' + content_type).encode(), b'', file_bytes,
             ('--' + boundary).encode(),
             b'Content-Disposition: form-data; name="name"', b'', name.encode(),
             ('--' + boundary + '--').encode(), b'']
    req = urllib.request.Request(EL_KB_FILE_URL, data=nl.join(parts), method='POST')
    req.add_header('xi-api-key', el_key)
    req.add_header('Content-Type', 'multipart/form-data; boundary=' + boundary)
    doc = json.loads(urllib.request.urlopen(req, timeout=180).read().decode('utf-8'))
    return doc.get('id')


def el_patch_agent_cc(el_key, agent_id, cc):
    pbody = json.dumps({'conversation_config': cc}).encode('utf-8')
    preq = urllib.request.Request(EL_AGENT_URL + urllib.parse.quote(agent_id), data=pbody, method='PATCH')
    preq.add_header('xi-api-key', el_key)
    preq.add_header('Content-Type', 'application/json')
    urllib.request.urlopen(preq, timeout=120).read()


def insert_into_menu(prompt_text, new_line):
    new_name = new_line.strip()[2:].strip()
    lower_new = new_name.lower()
    if '\n' in prompt_text:
        lines = prompt_text.split('\n')
        start = next((i for i, ln in enumerate(lines) if ln.strip().startswith('# COURSE MENU')), None)
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


def build_course_block(n, title, total, pdf_filename, txt_filename, course_type, audience,
                       section_text, teaching_text):
    """Build one Teacher COURSE LIBRARY profile block (list of lines, no trailing blank)."""
    lines = [DIVIDER, f'# COURSE #{n} — {title}', DIVIDER,
             f'Course Title: {title}',
             f'Total Slides: {total}',
             f'Slide Content File (PDF): {pdf_filename}',
             f'Teaching Notes File (TXT): {txt_filename}',
             f'Course Type: {course_type}',
             f'Audience: {audience}',
             'SECTION MAP:']
    secs = clean_lines(section_text)
    lines += ['- ' + s for s in secs] if secs else ['- Full Course (slides 1-%s)' % total]
    lines.append('TEACHING NOTES:')
    notes = clean_lines(teaching_text)
    lines += ['- ' + s for s in notes] if notes else ['- (none provided)']
    return lines


def _course_header_re():
    return re.compile(r'^#\s*COURSE\s*#(\d+)\b')


def find_course_blocks(lines):
    """
    Return a list of blocks: {num, hdr, top, start, end}
      top   = index of the divider line just above the header (or hdr if none)
      start = header line index
      end   = index ONE PAST the last line of this block's body
    A block's body runs until the next block's 'top', or the next major
    '# ====' section, or end of prompt.
    """
    hdr_re = _course_header_re()
    headers = []
    for i, ln in enumerate(lines):
        m = hdr_re.match(ln.strip())
        if m:
            headers.append((i, int(m.group(1))))
    blocks = []
    for idx, (hi, num) in enumerate(headers):
        top = hi
        if hi - 1 >= 0 and lines[hi - 1].strip().startswith('# --'):
            top = hi - 1
        if idx + 1 < len(headers):
            next_hi = headers[idx + 1][0]
            end = next_hi - 1 if (next_hi - 1 >= 0 and lines[next_hi - 1].strip().startswith('# --')) else next_hi
        else:
            # last course block: runs until the next major '# ====' section or end
            end = len(lines)
            for j in range(hi + 1, len(lines)):
                if lines[j].strip().startswith('# ===') or lines[j].strip().startswith('# COURSE LIBRARY'):
                    end = j
                    break
        blocks.append({'num': num, 'hdr': hi, 'top': top, 'start': top, 'end': end})
    return blocks


def insert_teacher_course(prompt_text, n, pdf_filename, block_lines):
    """
    Insert (or replace) a COURSE #n block inside the prompt's COURSE LIBRARY,
    keeping blocks in ascending number order. Re-run safe:
      - if a block with the same number OR same PDF filename exists, replace it.
    Returns (new_prompt, status) where status is 'inserted', 'replaced',
    or 'library_not_found'.
    """
    if '# COURSE LIBRARY' not in prompt_text:
        return prompt_text, 'library_not_found'

    lines = prompt_text.split('\n')
    blocks = find_course_blocks(lines)

    # Remove any existing block matching this number or this PDF filename.
    replaced = False
    to_remove = None
    for b in blocks:
        body = '\n'.join(lines[b['start']:b['end']])
        if b['num'] == n or pdf_filename in body:
            to_remove = b
            break
    if to_remove:
        del lines[to_remove['start']:to_remove['end']]
        replaced = True
        blocks = find_course_blocks(lines)  # recompute after removal

    # Decide insertion index (line number) to keep ascending order.
    insert_at = None
    for b in blocks:
        if b['num'] > n:
            insert_at = b['start']
            break
    if insert_at is None:
        if blocks:
            insert_at = blocks[-1]['end']
        else:
            # No course blocks yet: insert right after the COURSE LIBRARY intro,
            # i.e., after the last line before the first major divider following the header.
            lib_idx = next(i for i, ln in enumerate(lines) if ln.strip().startswith('# COURSE LIBRARY'))
            insert_at = len(lines)
            for j in range(lib_idx + 1, len(lines)):
                if lines[j].strip().startswith('# ==='):
                    insert_at = j
                    break

    new_lines = lines[:insert_at] + block_lines + lines[insert_at:]
    return '\n'.join(new_lines), ('replaced' if replaced else 'inserted')


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        steps = []

        def record(name, status, detail=''):
            steps.append({'step': name, 'status': status, 'detail': detail})

        try:
            length = int(self.headers.get('Content-Length', 0))
            payload = json.loads(self.rfile.read(length).decode('utf-8')) if length else {}

            tenant_name = str(payload.get('tenant', '')).strip()
            card, tenant_err = resolve_tenant(tenant_name)
            if tenant_err:
                record('setup', 'failed', tenant_err)
                return self._finish(False, steps, None)
            if tenant_name:
                record('0_tenant', 'selected', card.get('label') or tenant_name)

            token = card['github_token']
            el_key = card['elevenlabs_api_key']
            cc_key = os.environ.get('CLOUDCONVERT_API_KEY', '').strip()
            gh_owner = card['github_owner']
            gh_repo = card['github_repo']
            teacher_agent_default = card['teacher_agent_id']
            recommender_agent_default = card['recommender_agent_id']
            raw_root = 'https://raw.githubusercontent.com/%s/%s/%s/' % (gh_owner, gh_repo, BRANCH)

            job_id = str(payload.get('job_id', '')).strip()
            pdf_filename = str(payload.get('pdf_filename', '')).strip()
            txt_filename = str(payload.get('txt_filename', '')).strip()
            txt_content = payload.get('txt_content', '')
            course_title = str(payload.get('course_title', '')).strip()
            course_type = str(payload.get('course_type', '')).strip() or '(not specified)'
            audience = str(payload.get('audience', '')).strip() or '(not specified)'
            section_map = payload.get('section_map', '')
            teaching_notes = payload.get('teaching_notes', '')
            total_slides = int(payload.get('total_slides', 0) or 0)
            player_base = str(payload.get('player_base', '')).strip()
            rec_agent_id = str(payload.get('agent_id', '') or recommender_agent_default).strip()

            missing = [k for k, v in {
                'job_id': job_id, 'pdf_filename': pdf_filename, 'txt_filename': txt_filename,
                'txt_content': txt_content, 'course_title': course_title, 'player_base': player_base
            }.items() if not v]
            if missing:
                record('setup', 'failed', 'Missing: ' + ', '.join(missing))
                return self._finish(False, steps, None)
            if not (token and el_key and cc_key):
                record('setup', 'failed', 'One or more API keys are not set.')
                return self._finish(False, steps, None)

            course_id = slugify(course_title)
            pdf_url = raw_root + pdf_filename
            pdf_bytes = None

            # ---------- STEP 1: PDF -> repo ----------
            try:
                info = json.loads(http_get_bytes(
                    CC_SYNC_ROOT + urllib.parse.quote(job_id),
                    {'Authorization': 'Bearer ' + cc_key}).decode('utf-8'))
                tasks = info.get('data', {}).get('tasks', [])
                src_url = None
                for t in tasks:
                    if t.get('operation') == 'export/url' and t.get('status') == 'finished':
                        for f in ((t.get('result') or {}).get('files') or []):
                            if (f.get('filename') or '').lower().endswith('.pdf'):
                                src_url = f.get('url')
                                break
                    if src_url:
                        break
                if not src_url:
                    raise RuntimeError('No finished PDF found for that job_id (it may have expired).')
                pdf_bytes = http_get_bytes(src_url)
                sha = None
                try:
                    meta = json.loads(http_get_bytes(
                        f'{API_ROOT}/repos/{gh_owner}/{gh_repo}/contents/{urllib.parse.quote(pdf_filename)}?ref={BRANCH}',
                        gh_headers(token), 30).decode('utf-8'))
                    sha = meta.get('sha')
                except urllib.error.HTTPError as e:
                    if e.code != 404:
                        raise
                body = {'message': f'Add course PDF: {pdf_filename}',
                        'content': base64.b64encode(pdf_bytes).decode('ascii'), 'branch': BRANCH}
                if sha:
                    body['sha'] = sha
                req = urllib.request.Request(
                    f'{API_ROOT}/repos/{gh_owner}/{gh_repo}/contents/{urllib.parse.quote(pdf_filename)}',
                    data=json.dumps(body).encode('utf-8'), headers=gh_headers(token), method='PUT')
                urllib.request.urlopen(req, timeout=60).read()
                record('1_pdf', 'pushed', f'{pdf_filename} ({len(pdf_bytes)} bytes)')
            except Exception as e:
                record('1_pdf', 'failed', str(e))
                return self._finish(False, steps, None)

            # ---------- STEP 2: courses.json ----------
            try:
                sections, problems = parse_sections(section_map)
                if problems:
                    raise RuntimeError('Section lines missing a slide number: ' + '; '.join(problems))
                if not sections:
                    sections = [{'label': f'Full Course (slides 1-{total_slides})', 'startSlide': 1}]
                meta = json.loads(http_get_bytes(
                    f'{API_ROOT}/repos/{gh_owner}/{gh_repo}/contents/{COURSES_PATH}?ref={BRANCH}',
                    gh_headers(token), 30).decode('utf-8'))
                data = json.loads(base64.b64decode(meta['content']).decode('utf-8'))
                csha = meta['sha']
                entry = {'id': course_id, 'title': course_title, 'totalSlides': total_slides,
                         'pdfUrl': pdf_url,
                         'firstMessage': f'Welcome to {course_title}. Are you ready to begin?',
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
                body = {'message': f'Publish course #{course_number}: {course_title}',
                        'content': base64.b64encode(text.encode('utf-8')).decode('ascii'),
                        'branch': BRANCH, 'sha': csha}
                req = urllib.request.Request(
                    f'{API_ROOT}/repos/{gh_owner}/{gh_repo}/contents/{COURSES_PATH}',
                    data=json.dumps(body).encode('utf-8'), headers=gh_headers(token), method='PUT')
                urllib.request.urlopen(req, timeout=30).read()
                record('2_courses_json', cj_status, f'course #{course_number}')
            except Exception as e:
                record('2_courses_json', 'failed', str(e))
                return self._finish(False, steps, None)

            # ---------- STEP 3: RECOMMENDER (KB + menu) ----------
            try:
                agent = el_get_agent(el_key, rec_agent_id)
                cc = agent.get('conversation_config', {})
                prompt_obj = cc.get('agent', {}).get('prompt', {})
                kb_list = prompt_obj.get('knowledge_base', [])
                if not isinstance(kb_list, list):
                    kb_list = []
                prompt_text = prompt_obj.get('prompt', '')
                changed = False
                if any(isinstance(it, dict) and it.get('name') == txt_filename for it in kb_list):
                    kb_status = 'already_attached'
                else:
                    doc_id = el_create_doc(el_key, txt_filename, txt_content.encode('utf-8'), 'text/plain')
                    kb_list.append({'type': 'file', 'name': txt_filename, 'id': doc_id, 'usage_mode': 'auto'})
                    kb_status = 'attached'
                    changed = True
                new_prompt, menu_status = insert_into_menu(prompt_text, '- ' + txt_filename)
                if menu_status in ('inserted', 'inserted_unsorted'):
                    changed = True
                if changed:
                    prompt_obj['knowledge_base'] = kb_list
                    prompt_obj['prompt'] = new_prompt
                    cc['agent']['prompt'] = prompt_obj
                    el_patch_agent_cc(el_key, rec_agent_id, cc)
                record('3_recommender_kb', kb_status, '')
                record('3_recommender_menu', menu_status, '')
            except Exception as e:
                record('3_recommender', 'failed', str(e))
                return self._finish(False, steps, None)

            # ---------- STEP 4: TEACHER (PDF + TXT + profile block) ----------
            try:
                t_agent = el_get_agent(el_key, teacher_agent_default)
                tcc = t_agent.get('conversation_config', {})
                t_prompt_obj = tcc.get('agent', {}).get('prompt', {})
                t_kb = t_prompt_obj.get('knowledge_base', [])
                if not isinstance(t_kb, list):
                    t_kb = []
                t_prompt_text = t_prompt_obj.get('prompt', '') or ''
                t_changed = False
                existing_names = {it.get('name') for it in t_kb if isinstance(it, dict)}

                if pdf_filename in existing_names:
                    pdf_stat = 'already_attached'
                else:
                    pdf_doc_id = el_create_doc(el_key, pdf_filename, pdf_bytes, 'application/pdf')
                    t_kb.append({'type': 'file', 'name': pdf_filename, 'id': pdf_doc_id, 'usage_mode': 'auto'})
                    pdf_stat = 'attached'
                    t_changed = True

                if txt_filename in existing_names:
                    txt_stat = 'already_attached'
                else:
                    txt_doc_id = el_create_doc(el_key, txt_filename, txt_content.encode('utf-8'), 'text/plain')
                    t_kb.append({'type': 'file', 'name': txt_filename, 'id': txt_doc_id, 'usage_mode': 'auto'})
                    txt_stat = 'attached'
                    t_changed = True

                block_lines = build_course_block(
                    int(course_number), course_title, total_slides, pdf_filename, txt_filename,
                    course_type, audience, section_map, teaching_notes)
                new_t_prompt, profile_status = insert_teacher_course(
                    t_prompt_text, int(course_number), pdf_filename, block_lines)
                if profile_status in ('inserted', 'replaced'):
                    t_changed = True

                if t_changed:
                    t_prompt_obj['knowledge_base'] = t_kb
                    t_prompt_obj['prompt'] = new_t_prompt
                    tcc['agent']['prompt'] = t_prompt_obj
                    el_patch_agent_cc(el_key, teacher_agent_default, tcc)

                record('4_teacher_pdf', pdf_stat, pdf_filename)
                record('4_teacher_txt', txt_stat, txt_filename)
                record('4_teacher_profile', profile_status, f'COURSE #{course_number}')
            except Exception as e:
                record('4_teacher', 'failed', str(e))
                return self._finish(False, steps, None)

            # ---------- STEP 5: live link ----------
            live_url = player_base.rstrip('/') + '/?course=' + course_number
            record('5_live_link', 'built', live_url)
            return self._finish(True, steps, live_url, course_number)

        except Exception as e:
            record('unexpected', 'failed', str(e))
            return self._finish(False, steps, None)

    def _finish(self, ok, steps, live_url, course_number=None):
        payload = {'ok': ok,
                   'summary': ('Course is live.' if ok else 'Stopped at a failed step — fix it and run again.'),
                   'checklist': steps}
        if ok and live_url:
            payload['test_link'] = live_url
            payload['course_number'] = course_number
        return self._send(200 if ok else 502, payload)

    def _send(self, code, obj):
        body = json.dumps(obj, indent=2, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
