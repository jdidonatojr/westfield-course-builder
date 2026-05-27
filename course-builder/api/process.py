"""
AILA Course Builder — Step 4 of the upload flow (v7.1)

Returns JSON with text content + a Vercel-hosted PDF URL.
The browser fetches the PDF from /api/get_pdf which streams from
CloudConvert, then builds the ZIP locally. This avoids the 4.5 MB
fixed-response limit AND CloudConvert URL expiration issues.

POST /api/process
  JSON body:
    {
      "job_id": "...",
      "slide_data": { ... },
      "fields": { ... }
    }

Returns: JSON
    {
      "job_id": "...",            (browser passes back to /api/get_pdf)
      "pdf_filename": "...",
      "txt_filename": "...",
      "txt_content": "...",
      "elevenlabs_snippet": "...",
      "yola_snippet": "...",
      "checklist": "...",
      "filename_base": "..."
    }
"""

import os
import sys
import json
import time
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '_lib'))
from processor import (
    build_txt_file_from_data,
    build_elevenlabs_snippet,
    build_yola_snippet,
    build_checklist,
    make_filename
)


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            raw_body = self.rfile.read(content_length)
            payload = json.loads(raw_body.decode('utf-8'))

            for key in ['job_id', 'slide_data', 'fields']:
                if key not in payload:
                    self._send_error(400, f'Missing required field: {key}')
                    return

            fields = payload['fields']
            slide_data = payload['slide_data']

            required = [
                'course_number', 'course_title', 'course_type',
                'audience', 'section_map', 'teaching_notes'
            ]
            for f in required:
                if not fields.get(f, '').strip():
                    self._send_error(400, f'Missing required field: {f}')
                    return

            course_info = {
                'course_number': fields['course_number'].strip(),
                'course_title': fields['course_title'].strip(),
                'course_type': fields['course_type'].strip(),
                'audience': fields['audience'].strip(),
                'section_map': [
                    line.strip() for line in fields['section_map'].splitlines()
                    if line.strip()
                ],
                'teaching_notes': [
                    line.strip() for line in fields['teaching_notes'].splitlines()
                    if line.strip()
                ]
            }

            total_slides = slide_data.get('totalSlides', len(slide_data['slides']))

            filename_base = make_filename(course_info['course_title'])
            pdf_filename = f"{filename_base}.pdf"
            txt_filename = f"{filename_base}.txt"

            txt_content = build_txt_file_from_data(
                course_info['course_title'],
                slide_data['slides']
            )
            elevenlabs_snippet = build_elevenlabs_snippet(
                course_info, total_slides, pdf_filename, txt_filename
            )
            yola_snippet = build_yola_snippet(
                course_info, total_slides, pdf_filename
            )
            checklist = build_checklist(
                course_info, pdf_filename, txt_filename
            )

            # Wait for CloudConvert to finish - browser will fetch via /api/get_pdf
            api_key = os.environ.get('CLOUDCONVERT_API_KEY', '')
            if not api_key:
                self._send_error(500, 'CloudConvert API key not configured.')
                return

            # Just wait until the job is finished; don't download anything here
            wait_for_job_finished(payload['job_id'], api_key)

            response_payload = {
                'job_id': payload['job_id'],
                'pdf_filename': pdf_filename,
                'txt_filename': txt_filename,
                'txt_content': txt_content,
                'elevenlabs_snippet': elevenlabs_snippet,
                'yola_snippet': yola_snippet,
                'checklist': checklist,
                'filename_base': filename_base
            }

            response_bytes = json.dumps(response_payload).encode('utf-8')

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(response_bytes)))
            self.end_headers()
            self.wfile.write(response_bytes)

        except Exception as e:
            self._send_error(500, f'Server error: {str(e)}')

    def _send_error(self, code, message):
        self.send_response(code)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(message.encode('utf-8'))


def wait_for_job_finished(job_id, api_key):
    """Poll CloudConvert until the job is finished. Doesn't download anything."""
    job_status_url = f'https://api.cloudconvert.com/v2/jobs/{job_id}'
    headers = {'Authorization': f'Bearer {api_key}'}

    max_attempts = 60
    for attempt in range(max_attempts):
        time.sleep(2)
        req = urllib.request.Request(job_status_url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as response:
            job_data = json.loads(response.read().decode('utf-8'))['data']

        status = job_data['status']
        if status == 'finished':
            return
        if status == 'error':
            raise Exception('CloudConvert job failed.')

    raise Exception('CloudConvert job timed out.')
