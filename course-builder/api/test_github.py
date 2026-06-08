"""
AILA Course Builder — GitHub connection test (Increment 1, step 1)

A tiny, safe endpoint that proves the tool can WRITE to the test repo.
Visit /api/test_github in your browser. It writes a small file called
_connection_test.txt to the aila-course-files-test repo and reports back.

If this works, the token + permissions + API call are all correct, and
we can build the real publish step on top of it.

GET /api/test_github
Returns: JSON { ok, action, path, html_url, message }
"""

import os
import json
import base64
import time
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler

# --- Where we write (the TEST content repo only) ---
OWNER = 'jdidonatojr'
REPO = 'aila-course-files-test'
BRANCH = 'main'
TEST_PATH = '_connection_test.txt'

API_ROOT = 'https://api.github.com'


def gh_headers(token):
    return {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'aila-course-builder',
        'Content-Type': 'application/json',
    }


def get_existing_sha(token, path):
    """Return the file's current sha if it exists, else None."""
    url = f'{API_ROOT}/repos/{OWNER}/{REPO}/contents/{path}?ref={BRANCH}'
    req = urllib.request.Request(url, headers=gh_headers(token), method='GET')
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return data.get('sha')
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None  # file doesn't exist yet — that's fine
        raise


def put_file(token, path, text, sha=None):
    """Create or update a text file in the repo."""
    url = f'{API_ROOT}/repos/{OWNER}/{REPO}/contents/{path}'
    body = {
        'message': 'Connection test from the course builder',
        'content': base64.b64encode(text.encode('utf-8')).decode('ascii'),
        'branch': BRANCH,
    }
    if sha:
        body['sha'] = sha
    req = urllib.request.Request(
        url, data=json.dumps(body).encode('utf-8'),
        headers=gh_headers(token), method='PUT'
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode('utf-8'))


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            token = os.environ.get('GITHUB_TOKEN', '').strip()
            if not token:
                self._send(500, {'ok': False,
                    'message': 'GITHUB_TOKEN is not set on this project.'})
                return

            existing = get_existing_sha(token, TEST_PATH)
            stamp = time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())
            text = f'Course builder connection test. Last write: {stamp}\n'
            result = put_file(token, TEST_PATH, text, sha=existing)

            self._send(200, {
                'ok': True,
                'action': 'updated' if existing else 'created',
                'path': TEST_PATH,
                'html_url': result.get('content', {}).get('html_url', ''),
                'message': 'Success — the builder can write to the test repo.'
            })

        except urllib.error.HTTPError as e:
            detail = e.read().decode('utf-8', errors='replace')[:300]
            self._send(500, {'ok': False,
                'message': f'GitHub API error ({e.code}): {detail}'})
        except Exception as e:
            self._send(500, {'ok': False, 'message': f'Server error: {str(e)}'})

    def _send(self, code, obj):
        body = json.dumps(obj, indent=2).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
