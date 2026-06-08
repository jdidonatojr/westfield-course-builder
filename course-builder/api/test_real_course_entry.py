"""
AILA Course Builder — Increment 3, sub-step 3.1

Builds the REAL courses.json entry from form-style data (title + sections),
replacing the earlier placeholder logic.

For easy browser testing, realistic DEFAULTS are preloaded for the
"Practicing Difficult Conversations with AI" course. Override any of them
with query params if you want, but you don't have to:
   ?title=...        course title
   ?pdf=...          pdf filename (already in the test repo)
   ?total_slides=NN  slide count
   ?sections=A~B~C   sections separated by ~  (each like "Intro (slides 1-3)")

How to test:
  https://aila-course-files.vercel.app/api/test_real_course_entry

What it does:
  - Parses sections (start slide = first number inside the LAST parentheses).
  - Builds the entry: id (slug), title, totalSlides, pdfUrl, firstMessage, sections.
  - Writes courses.json in the TEST repo:
      * if a PLACEHOLDER (title starts "TEST —") points at this PDF, it is
        removed and the real course is created at the smallest unused number;
      * if a REAL entry for this PDF exists, it is updated in place (re-run safe);
      * otherwise it is added at the smallest unused number.

Returns the entry it wrote.
"""

import os
import re
import json
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

# ---- Preloaded realistic defaults for easy testing ----
DEFAULT_TITLE = 'Practicing Difficult Conversations with AI'
DEFAULT_PDF = 'Practicing-Difficult-Conversations-with-AI.pdf'
DEFAULT_TOTAL_SLIDES = 12
DEFAULT_SECTIONS = [
    'Opening and Welcome (slides 1-2)',
    'Why Difficult Conversations Matter (3-5)',
    'The Role-Play Method (6-8)',
    'Practicing with AI (9-11)',
    'Recap and Next Steps (12)',
]


def gh_headers(token):
    return {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'aila-course-builder',
        'Content-Type': 'application/json',
    }


def slugify(text):
    return re.sub(r'[^a-zA-Z0-9]+', '_', text).strip('_').lower()


def parse_sections(lines):
    """Start slide = first number inside the LAST (...) group. Returns (sections, problems)."""
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


def get_courses(token):
    url = f'{API_ROOT}/repos/{OWNER}/{REPO}/contents/{COURSES_PATH}?ref={BRANCH}'
    req = urllib.request.Request(url, headers=gh_headers(token), method='GET')
    with urllib.request.urlopen(req, timeout=30) as resp:
        meta = json.loads(resp.read().decode('utf-8'))
    data = json.loads(base64.b64decode(meta['content']).decode('utf-8'))
    return data, meta['sha']


def put_courses(token, data, sha):
    text = json.dumps(data, indent=2, ensure_ascii=False) + '\n'
    url = f'{API_ROOT}/repos/{OWNER}/{REPO}/contents/{COURSES_PATH}'
    body = {
        'message': 'Update courses.json (3.1 real course entry)',
        'content': base64.b64encode(text.encode('utf-8')).decode('ascii'),
        'branch': BRANCH,
        'sha': sha,
    }
    req = urllib.request.Request(url, data=json.dumps(body).encode('utf-8'),
                                 headers=gh_headers(token), method='PUT')
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode('utf-8'))


def smallest_unused(keys):
    used = set(int(k) for k in keys if str(k).isdigit())
    n = 1
    while n in used:
        n += 1
    return str(n)


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            token = os.environ.get('GITHUB_TOKEN', '').strip()
            if not token:
                return self._send(500, {'ok': False,
                    'message': 'GITHUB_TOKEN is not set on this project.'})

            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            title = q.get('title', [DEFAULT_TITLE])[0].strip()
            pdf = q.get('pdf', [DEFAULT_PDF])[0].strip()
            total_slides = int(q.get('total_slides', [str(DEFAULT_TOTAL_SLIDES)])[0])
            if 'sections' in q:
                section_lines = q['sections'][0].split('~')
            else:
                section_lines = DEFAULT_SECTIONS

            # Parse sections (and stop if any line lacks a slide number).
            sections, problems = parse_sections(section_lines)
            if problems:
                return self._send(400, {'ok': False,
                    'message': 'Some section lines have no slide number in parentheses.',
                    'problem_lines': problems})

            pdf_url = RAW_ROOT + pdf
            entry = {
                'id': slugify(title),
                'title': title,
                'totalSlides': total_slides,
                'pdfUrl': pdf_url,
                'firstMessage': f'Welcome to {title}. Are you ready to begin?',
                'sections': sections,
            }

            # Read courses.json and decide where the entry goes.
            data, sha = get_courses(token)

            existing_key = None
            existing_is_placeholder = False
            for k, v in data.items():
                if isinstance(v, dict) and v.get('pdfUrl') == pdf_url:
                    existing_key = k
                    title_v = str(v.get('title', ''))
                    existing_is_placeholder = title_v.startswith('TEST —') or title_v.startswith('TEST -')
                    break

            if existing_key is not None and not existing_is_placeholder:
                # Real entry already there -> update in place (re-run safe).
                course_number = existing_key
                action = 'updated_in_place'
            else:
                # Remove a placeholder if present, then use smallest unused number.
                if existing_key is not None and existing_is_placeholder:
                    del data[existing_key]
                course_number = smallest_unused(data.keys())
                action = 'created_real' + ('_replaced_placeholder' if existing_key else '')

            data[course_number] = entry
            put_courses(token, data, sha)

            return self._send(200, {
                'ok': True,
                'action': action,
                'course_number': course_number,
                'entry': entry,
                'message': 'courses.json updated with REAL course data.'
            })

        except urllib.error.HTTPError as e:
            detail = ''
            try:
                detail = e.read().decode('utf-8', errors='replace')[:300]
            except Exception:
                pass
            return self._send(502, {'ok': False, 'message': f'API error ({e.code}): {detail}'})
        except Exception as e:
            return self._send(500, {'ok': False, 'message': f'Server error: {str(e)}'})

    def _send(self, code, obj):
        body = json.dumps(obj, indent=2, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
