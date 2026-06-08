"""
AILA Course Builder — Step 2c test endpoint

What it does:
  1. Takes a CloudConvert job_id (to learn the PDF's exact filename).
  2. Reads courses.json from the TEST content repo.
  3. Adds (or updates) a course entry that points at that PDF.
  4. Writes courses.json back, keeping the file valid and tidy.

For this TEST, title / id / firstMessage / sections / totalSlides are
clearly-marked PLACEHOLDERS. Only pdfUrl is built for real. The real
title + sections get filled in later (Increment 3) from the builder.

Safe to re-run: if an entry for this PDF already exists, it updates that
entry instead of adding a new number.

How to test in a browser:
  https://aila-course-files.vercel.app/api/test_update_courses?job_id=YOUR_JOB_ID

Returns JSON: { ok, action, course_number, entry, message }
"""

import os
import re
import json
import base64
import urllib.parse
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler

# --- Where we write (the TEST content repo only) ---
OWNER = 'jdidonatojr'
REPO = 'aila-course-files-test'
BRANCH = 'main'
COURSES_PATH = 'courses.json'

API_ROOT = 'https://api.github.com'
CC_SYNC_ROOT = 'https://sync.api.cloudconvert.com/v2/jobs/'
RAW_ROOT = f'https://raw.githubusercontent.com/{OWNER}/{REPO}/{BRANCH}/'


def gh_headers(token):
    return {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'aila-course-builder',
        'Content-Type': 'application/json',
    }


def get_pdf_filename(cc_key, job_id):
    """Wait for the job to finish, then return the PDF's filename."""
    url = CC_SYNC_ROOT + urllib.parse.quote(job_id)
    req = urllib.request.Request(url)
    req.add_header('Authorization', 'Bearer ' + cc_key)
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = json.loads(resp.read().decode('utf-8'))

    data = body.get('data', {})
    if data.get('status') == 'error':
        raise RuntimeError('CloudConvert reported the job failed.')

    tasks = data.get('tasks', [])
    for t in tasks:
        if t.get('name') == 'export-pdf' and t.get('status') == 'finished':
            files = (t.get('result') or {}).get('files') or []
            if files:
                return files[0].get('filename')
    for t in tasks:
        if t.get('operation') == 'export/url' and t.get('status') == 'finished':
            files = (t.get('result') or {}).get('files') or []
            for f in files:
                if (f.get('filename') or '').lower().endswith('.pdf'):
                    return f.get('filename')
    return None


def get_courses(token):
    """Read courses.json. Returns (data_dict, sha)."""
    url = f'{API_ROOT}/repos/{OWNER}/{REPO}/contents/{COURSES_PATH}?ref={BRANCH}'
    req = urllib.request.Request(url, headers=gh_headers(token), method='GET')
    with urllib.request.urlopen(req, timeout=30) as resp:
        meta = json.loads(resp.read().decode('utf-8'))
    raw = base64.b64decode(meta['content']).decode('utf-8')
    return json.loads(raw), meta['sha']


def put_courses(token, data, sha):
    """Write courses.json back, pretty-printed and UTF-8 clean."""
    text = json.dumps(data, indent=2, ensure_ascii=False) + '\n'
    url = f'{API_ROOT}/repos/{OWNER}/{REPO}/contents/{COURSES_PATH}'
    body = {
        'message': 'Update courses.json (2c test entry)',
        'content': base64.b64encode(text.encode('utf-8')).decode('ascii'),
        'branch': BRANCH,
        'sha': sha,
    }
    req = urllib.request.Request(
        url, data=json.dumps(body).encode('utf-8'),
        headers=gh_headers(token), method='PUT'
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode('utf-8'))


def slugify(text):
    """Lowercase; turn anything that isn't a letter/number into one underscore."""
    s = re.sub(r'[^a-zA-Z0-9]+', '_', text).strip('_').lower()
    return s


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            cc_key = os.environ.get('CLOUDCONVERT_API_KEY', '').strip()
            token = os.environ.get('GITHUB_TOKEN', '').strip()
            if not cc_key:
                return self._send(500, {'ok': False,
                    'message': 'CLOUDCONVERT_API_KEY is not set on this project.'})
            if not token:
                return self._send(500, {'ok': False,
                    'message': 'GITHUB_TOKEN is not set on this project.'})

            query = urllib.parse.urlparse(self.path).query
            params = urllib.parse.parse_qs(query)
            job_id = params.get('job_id', [''])[0].strip()
            if not job_id:
                return self._send(400, {'ok': False,
                    'message': 'Please add ?job_id=... to the web address.'})

            # 1. Get the PDF filename.
            filename = get_pdf_filename(cc_key, job_id)
            if not filename:
                return self._send(404, {'ok': False,
                    'message': 'Job finished but no PDF filename was found.'})

            # 2. Build the entry. pdfUrl is REAL; the rest are placeholders.
            stem = filename[:-4] if filename.lower().endswith('.pdf') else filename
            readable = stem.replace('-', ' ').replace('_', ' ').strip()
            test_title = 'TEST — ' + readable
            pdf_url = RAW_ROOT + filename

            entry = {
                'id': slugify(test_title),
                'title': test_title,
                'totalSlides': 0,  # placeholder — real count comes in Increment 3
                'pdfUrl': pdf_url,
                'firstMessage': f'Welcome to {test_title}. Are you ready to begin?',
                'sections': [
                    {'label': 'TEST placeholder section (slides 1-1)', 'startSlide': 1}
                ],
            }

            # 3. Read courses.json.
            data, sha = get_courses(token)

            # 4. If this PDF is already listed, update that entry in place.
            #    Otherwise, add it as the next number.
            existing_key = None
            for k, v in data.items():
                if isinstance(v, dict) and v.get('pdfUrl') == pdf_url:
                    existing_key = k
                    break

            if existing_key is not None:
                course_number = existing_key
                action = 'updated'
            else:
                # Pick the smallest whole number not already used (1, 2, 3, ...).
                used = set(int(k) for k in data.keys() if str(k).isdigit())
                n = 1
                while n in used:
                    n += 1
                course_number = str(n)
                action = 'created'

            data[course_number] = entry

            # 5. Write it back.
            put_courses(token, data, sha)

            return self._send(200, {
                'ok': True,
                'action': action,
                'course_number': course_number,
                'entry': entry,
                'message': 'Success — courses.json updated in the test repo.'
            })

        except urllib.error.HTTPError as e:
            detail = ''
            try:
                detail = e.read().decode('utf-8', errors='replace')[:300]
            except Exception:
                pass
            return self._send(502, {'ok': False,
                'message': f'API error ({e.code}): {detail}'})
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
