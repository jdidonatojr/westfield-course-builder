"""
AILA Course Builder — Step 4 of the upload flow

The browser has already:
  - Read the .pptx and extracted slide data (text + notes + hidden flag)
  - Uploaded the .pptx directly to CloudConvert

Now we receive a small JSON payload with the slide data and form fields,
wait for CloudConvert to finish the PDF conversion, and build the ZIP.

POST /api/process
  JSON body:
    {
      "job_id": "...",
      "slide_data": {
        "slides": [{ "visible": "...", "notes": "...", "hidden": false }, ...],
        "totalSlides": N,
        "hiddenCount": N
      },
      "fields": {
        "course_number": "...",
        "course_title": "...",
        "course_type": "...",
        "audience": "...",
        "section_map": "line1\nline2\n...",
        "teaching_notes": "line1\nline2\n..."
      }
    }

Returns: application/zip download
"""

import os
import sys
import json
import io
import zipfile
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

            # Validate required fields
            for key in ['job_id', 'slide_data', 'fields']:
                if key not in payload:
                    self._send_error(400, f'Missing required field: {key}')
                    return

            fields = payload['fields']
            slide_data = payload['slide_data']

            required_text_fields = [
                'course_number', 'course_title', 'course_type',
                'audience', 'section_map', 'teaching_notes'
            ]
            for f in required_text_fields:
                if not fields.get(f, '').strip():
                    self._send_error(400, f'Missing required field: {f}')
                    return

            # Build course info
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

            # Build all the text outputs
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

            # Wait for CloudConvert and download the PDF
            api_key = os.environ.get('CLOUDCONVERT_API_KEY', '')
            if not api_key:
                self._send_error(500, 'CloudConvert API key not configured.')
                return

            pdf_bytes = wait_for_pdf(payload['job_id'], api_key)

            # Build the ZIP
            zip_bytes = build_zip(
                pdf_filename, pdf_bytes,
                txt_filename, txt_content,
                elevenlabs_snippet, yola_snippet, checklist
            )

            # Send response
            self.send_response(200)
            self.send_header('Content-Type', 'application/zip')
            self.send_header(
                'Content-Disposition',
                f'attachment; filename="{filename_base}-package.zip"'
            )
            self.send_header('Content-Length', str(len(zip_bytes)))
            self.end_headers()
            self.wfile.write(zip_bytes)

        except Exception as e:
            self._send_error(500, f'Server error: {str(e)}')

    def _send_error(self, code, message):
        self.send_response(code)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(message.encode('utf-8'))


def wait_for_pdf(job_id, api_key):
    """Poll CloudConvert until the PDF is ready, then download it."""
    job_status_url = f'https://api.cloudconvert.com/v2/jobs/{job_id}'
    headers = {'Authorization': f'Bearer {api_key}'}

    max_attempts = 60
    for attempt in range(max_attempts):
        time.sleep(2)

        req = urllib.request.Request(job_status_url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as response:
            job_status_data = json.loads(response.read().decode('utf-8'))['data']

        status = job_status_data['status']

        if status == 'finished':
            for task in job_status_data['tasks']:
                if task['name'] == 'export-task' and task['status'] == 'finished':
                    pdf_url = task['result']['files'][0]['url']
                    with urllib.request.urlopen(pdf_url, timeout=120) as pdf_response:
                        return pdf_response.read()
            raise Exception('Job finished but no PDF URL found.')

        if status == 'error':
            raise Exception('CloudConvert job failed.')

    raise Exception('CloudConvert job timed out.')


def build_zip(pdf_filename, pdf_bytes, txt_filename, txt_content,
              elevenlabs_snippet, yola_snippet, checklist):
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(pdf_filename, pdf_bytes)
        zf.writestr(txt_filename, txt_content)
        zf.writestr('elevenlabs-snippet.txt', elevenlabs_snippet)
        zf.writestr('yola-snippet.txt', yola_snippet)
        zf.writestr('assembly-checklist.txt', checklist)
    return zip_buffer.getvalue()
