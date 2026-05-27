"""
AILA Course Builder — Step 2 of 2-step upload flow

After the browser has uploaded the .pptx directly to CloudConvert,
it calls this endpoint with the job_id and form fields. We wait for
the conversion to finish, download the PDF, run our processing engine,
and return the ZIP.

POST /api/process
  multipart form data:
    - job_id         (from /api/create_job response)
    - pptx           (the original .pptx file, used only for slide notes)
    - course_number  (string)
    - course_title   (string)
    - course_type    (string)
    - audience       (string)
    - section_map    (text, one section per line)
    - teaching_notes (text, one bullet per line)

Returns: application/zip download
"""

import os
import sys
import json
import io
import zipfile
import tempfile
import time
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler
from email.parser import BytesParser
from email.policy import default as email_default

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '_lib'))
from processor import process_deck


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            content_type = self.headers.get('Content-Type', '')

            if 'multipart/form-data' not in content_type:
                self._send_error(400, 'Expected multipart/form-data upload.')
                return

            raw_body = self.rfile.read(content_length)
            fields, files = parse_multipart(raw_body, content_type)

            # Validate required fields
            required_text_fields = [
                'job_id', 'course_number', 'course_title', 'course_type',
                'audience', 'section_map', 'teaching_notes'
            ]
            for f in required_text_fields:
                if not fields.get(f, '').strip():
                    self._send_error(400, f'Missing required field: {f}')
                    return

            if 'pptx' not in files:
                self._send_error(400, 'Missing required file: pptx')
                return

            # Save the .pptx to a temp file for slide-note extraction
            with tempfile.NamedTemporaryFile(suffix='.pptx', delete=False) as tmp:
                tmp.write(files['pptx']['content'])
                pptx_path = tmp.name

            try:
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

                # Run the deck processor to get all text content
                result = process_deck(pptx_path, course_info)

                # Wait for CloudConvert to finish and download the PDF
                api_key = os.environ.get('CLOUDCONVERT_API_KEY', '')
                if not api_key:
                    self._send_error(500, 'CloudConvert API key not configured.')
                    return

                pdf_bytes = wait_for_pdf(fields['job_id'].strip(), api_key)

                # Build the ZIP file
                zip_bytes = build_zip(result, pdf_bytes)

                # Send the ZIP back
                self.send_response(200)
                self.send_header('Content-Type', 'application/zip')
                self.send_header(
                    'Content-Disposition',
                    f'attachment; filename="{result["filename_base"]}-package.zip"'
                )
                self.send_header('Content-Length', str(len(zip_bytes)))
                self.end_headers()
                self.wfile.write(zip_bytes)

            finally:
                try:
                    os.unlink(pptx_path)
                except Exception:
                    pass

        except Exception as e:
            self._send_error(500, f'Server error: {str(e)}')

    def _send_error(self, code, message):
        self.send_response(code)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(message.encode('utf-8'))


# ============================================================
# Parse multipart/form-data into fields and files
# ============================================================
def parse_multipart(raw_body, content_type):
    header = f'Content-Type: {content_type}\r\n\r\n'.encode('utf-8')
    parser = BytesParser(policy=email_default)
    msg = parser.parsebytes(header + raw_body)

    fields = {}
    files = {}

    for part in msg.iter_parts():
        disposition = part.get('Content-Disposition', '')
        if not disposition:
            continue

        params = dict(part.get_params(header='Content-Disposition'))
        name = params.get('name', '')
        filename = params.get('filename')

        if filename:
            files[name] = {
                'filename': filename,
                'content': part.get_payload(decode=True)
            }
        else:
            content = part.get_payload(decode=True)
            if content is None:
                content = ''
            else:
                content = content.decode('utf-8', errors='replace')
            fields[name] = content

    return fields, files


# ============================================================
# Poll CloudConvert until the PDF is ready, then download it
# ============================================================
def wait_for_pdf(job_id, api_key):
    """
    Poll the CloudConvert job until it finishes, then download
    and return the PDF bytes.
    """
    job_status_url = f'https://api.cloudconvert.com/v2/jobs/{job_id}'
    headers = {'Authorization': f'Bearer {api_key}'}

    max_attempts = 60  # up to 2 minutes
    for attempt in range(max_attempts):
        time.sleep(2)

        req = urllib.request.Request(job_status_url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as response:
            job_status_data = json.loads(response.read().decode('utf-8'))['data']

        status = job_status_data['status']

        if status == 'finished':
            # Find the export-task and grab the PDF URL
            for task in job_status_data['tasks']:
                if task['name'] == 'export-task' and task['status'] == 'finished':
                    pdf_url = task['result']['files'][0]['url']
                    with urllib.request.urlopen(pdf_url, timeout=120) as pdf_response:
                        return pdf_response.read()
            raise Exception('Job finished but no PDF URL found.')

        if status == 'error':
            raise Exception('CloudConvert job failed.')

    raise Exception('CloudConvert job timed out.')


# ============================================================
# Build the ZIP file with all output pieces
# ============================================================
def build_zip(result, pdf_bytes):
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(result['pdf_filename'], pdf_bytes)
        zf.writestr(result['txt_filename'], result['txt_content'])
        zf.writestr('elevenlabs-snippet.txt', result['elevenlabs_snippet'])
        zf.writestr('yola-snippet.txt', result['yola_snippet'])
        zf.writestr('assembly-checklist.txt', result['checklist'])

    return zip_buffer.getvalue()
