"""
AILA Course Builder — Step 2b test endpoint

What it does:
  1. Takes a CloudConvert job_id.
  2. Waits for the job to finish and finds the converted PDF (same as 2a).
  3. Downloads that PDF.
  4. Pushes it into the TEST content repo (aila-course-files-test),
     in the main folder, using CloudConvert's exact filename.

How to test in a browser:
  https://aila-course-files.vercel.app/api/test_push_pdf?job_id=YOUR_JOB_ID

Returns JSON: { ok, action, filename, size_bytes, html_url, message }
"""

import os
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

API_ROOT = 'https://api.github.com'
CC_SYNC_ROOT = 'https://sync.api.cloudconvert.com/v2/jobs/'


def gh_headers(token):
    return {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'aila-course-builder',
        'Content-Type': 'application/json',
    }


def get_pdf_from_cloudconvert(cc_key, job_id):
    """Wait for the job to finish, then return (pdf_url, pdf_filename)."""
    url = CC_SYNC_ROOT + urllib.parse.quote(job_id)
    req = urllib.request.Request(url)
    req.add_header('Authorization', 'Bearer ' + cc_key)
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = json.loads(resp.read().decode('utf-8'))

    data = body.get('data', {})
    if data.get('status') == 'error':
        raise RuntimeError('CloudConvert reported the job failed.')

    tasks = data.get('tasks', [])

    # Prefer the task named "export-pdf"; otherwise any finished PDF export.
    for t in tasks:
        if t.get('name') == 'export-pdf' and t.get('status') == 'finished':
            files = (t.get('result') or {}).get('files') or []
            if files:
                return files[0].get('url'), files[0].get('filename')

    for t in tasks:
        if t.get('operation') == 'export/url' and t.get('status') == 'finished':
            files = (t.get('result') or {}).get('files') or []
            for f in files:
                if (f.get('filename') or '').lower().endswith('.pdf'):
                    return f.get('url'), f.get('filename')

    return None, None


def download_bytes(url):
    """Download a file and return its raw bytes."""
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def get_existing_sha(token, path):
    """Return the file's current sha if it already exists, else None."""
    url = f'{API_ROOT}/repos/{OWNER}/{REPO}/contents/{urllib.parse.quote(path)}?ref={BRANCH}'
    req = urllib.request.Request(url, headers=gh_headers(token), method='GET')
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return data.get('sha')
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None  # not there yet — that's fine
        raise


def put_pdf(token, path, raw_bytes, sha=None):
    """Create or update a PDF (binary) file in the repo."""
    url = f'{API_ROOT}/repos/{OWNER}/{REPO}/contents/{urllib.parse.quote(path)}'
    body = {
        'message': f'Add course PDF: {path}',
        'content': base64.b64encode(raw_bytes).decode('ascii'),
        'branch': BRANCH,
    }
    if sha:
        body['sha'] = sha
    req = urllib.request.Request(
        url, data=json.dumps(body).encode('utf-8'),
        headers=gh_headers(token), method='PUT'
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode('utf-8'))


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

            # Read job_id from the web address (?job_id=...).
            query = urllib.parse.urlparse(self.path).query
            params = urllib.parse.parse_qs(query)
            job_id = params.get('job_id', [''])[0].strip()
            if not job_id:
                return self._send(400, {'ok': False,
                    'message': 'Please add ?job_id=... to the web address.'})

            # 1. Find the PDF on CloudConvert.
            pdf_url, filename = get_pdf_from_cloudconvert(cc_key, job_id)
            if not pdf_url:
                return self._send(404, {'ok': False,
                    'message': 'Job finished but no PDF download link was found.'})

            # 2. Download the PDF.
            raw = download_bytes(pdf_url)

            # 3. Push it to the test repo (main folder = just the filename).
            existing = get_existing_sha(token, filename)
            result = put_pdf(token, filename, raw, sha=existing)

            return self._send(200, {
                'ok': True,
                'action': 'updated' if existing else 'created',
                'filename': filename,
                'size_bytes': len(raw),
                'html_url': result.get('content', {}).get('html_url', ''),
                'message': 'Success — the PDF is now in the test repo.'
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
        body = json.dumps(obj, indent=2).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
