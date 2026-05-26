"""
AILA Course Builder — Main API endpoint

Receives a .pptx upload + form fields, processes it, converts to PDF
via CloudConvert, and returns a ZIP file with everything.

POST /api/process
  multipart form data:
    - pptx           (file)
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
from http.server import BaseHTTPRequestHandler
from email.parser import BytesParser
from email.policy import default as email_default

# Make our _lib folder importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '_lib'))
from processor import process_deck


# ============================================================
# HANDLER
# ============================================================
class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            # ----- Parse the multipart form data -----
            content_length = int(self.headers.get('Content-Length', 0))
            content_type = self.headers.get('Content-Type', '')

            if 'multipart/form-data' not in content_type:
                self._send_error(400, 'Expected multipart/form-data upload.')
                return

            raw_body = self.rfile.read(content_length)
            fields, files = parse_multipart(raw_body, content_type)

            # ----- Validate required fields -----
            required_text_fields = [
                'course_number', 'course_title', 'course_type',
                'audience', 'section_map', 'teaching_notes'
            ]
            for f in required_text_fields:
                if not fields.get(f, '').strip():
                    self._send_error(400, f'Missing required field: {f}')
                    return

            if 'pptx' not in files:
                self._send_error(400, 'Missing required file: pptx')
                return

            # ----- Save the uploaded .pptx to a temp file -----
            with tempfile.NamedTemporaryFile(
                suffix='.pptx', delete=False
            ) as tmp:
                tmp.write(files['pptx']['content'])
                pptx_path = tmp.name

            try:
                # ----- Parse the editorial fields -----
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

                # ----- Run the processor -----
                result = process_deck(pptx_path, course_info)

                # ----- Convert .pptx to PDF via CloudConvert -----
                api_key = os.environ.get('CLOUDCONVERT_API_KEY', '')
                if not api_key:
                    self._send_error(
                        500,
                        'CloudConvert API key not configured on the server.'
                    )
                    return

                pdf_bytes = convert_to_pdf(pptx_path, api_key)

                # ----- Build the ZIP file in memory -----
                zip_bytes = build_zip(result, pdf_bytes)

                # ----- Send the ZIP as the response -----
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
                # Clean up the temp .pptx file
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
    """
    Parse a multipart/form-data POST body.
    Returns (fields_dict, files_dict).
    """
    # Build a fake email-style message so we can use Python's parser
    header = f'Content-Type: {content_type}\r\n\r\n'.encode('utf-8')
    parser = BytesParser(policy=email_default)
    msg = parser.parsebytes(header + raw_body)

    fields = {}
    files = {}

    for part in msg.iter_parts():
        disposition = part.get('Content-Disposition', '')
        if not disposition:
            continue

        # Pull out the field name
        params = dict(part.get_params(header='Content-Disposition'))
        name = params.get('name', '')
        filename = params.get('filename')

        if filename:
            # This is a file upload
            files[name] = {
                'filename': filename,
                'content': part.get_payload(decode=True)
            }
        else:
            # This is a regular field
            content = part.get_payload(decode=True)
            if content is None:
                content = ''
            else:
                content = content.decode('utf-8', errors='replace')
            fields[name] = content

    return fields, files


# ============================================================
# Convert .pptx to PDF using CloudConvert API
# ============================================================
def convert_to_pdf(pptx_path, api_key):
    """
    Send the .pptx to CloudConvert, wait for it to convert to PDF,
    and return the PDF bytes.

    Uses the v2 sync endpoint for simplicity.
    """
    import requests  # imported here to keep top-level imports clean

    # Step 1: create a job with import-upload → convert → export-url
    create_url = 'https://api.cloudconvert.com/v2/jobs'
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json'
    }

    job_payload = {
        'tasks': {
            'upload-task': {
                'operation': 'import/upload'
            },
            'convert-task': {
                'operation': 'convert',
                'input': 'upload-task',
                'input_format': 'pptx',
                'output_format': 'pdf'
            },
            'export-task': {
                'operation': 'export/url',
                'input': 'convert-task'
            }
        }
    }

    response = requests.post(create_url, json=job_payload, headers=headers, timeout=30)
    response.raise_for_status()
    job_data = response.json()['data']
    job_id = job_data['id']

    # Step 2: find the upload task and upload the file
    upload_task = None
    for task in job_data['tasks']:
        if task['name'] == 'upload-task':
            upload_task = task
            break

    upload_url = upload_task['result']['form']['url']
    upload_params = upload_task['result']['form']['parameters']

    with open(pptx_path, 'rb') as f:
        files_payload = {'file': (os.path.basename(pptx_path), f)}
        upload_response = requests.post(
            upload_url,
            data=upload_params,
            files=files_payload,
            timeout=120
        )
        upload_response.raise_for_status()

    # Step 3: poll the job until done
    job_status_url = f'https://api.cloudconvert.com/v2/jobs/{job_id}'
    max_attempts = 60  # up to 2 minutes
    for attempt in range(max_attempts):
        time.sleep(2)
        status_response = requests.get(job_status_url, headers=headers, timeout=30)
        status_response.raise_for_status()
        job_status_data = status_response.json()['data']
        status = job_status_data['status']

        if status == 'finished':
            # Find the export task and get the download URL
            for task in job_status_data['tasks']:
                if task['name'] == 'export-task' and task['status'] == 'finished':
                    pdf_url = task['result']['files'][0]['url']
                    pdf_response = requests.get(pdf_url, timeout=120)
                    pdf_response.raise_for_status()
                    return pdf_response.content
            raise Exception('Job finished but no PDF URL found.')

        if status == 'error':
            raise Exception('CloudConvert job failed.')

    raise Exception('CloudConvert job timed out.')


# ============================================================
# Build the ZIP file with all output pieces
# ============================================================
def build_zip(result, pdf_bytes):
    """
    Package everything into a ZIP file in memory.
    Returns the raw bytes of the ZIP.
    """
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        # The PDF (slides)
        zf.writestr(result['pdf_filename'], pdf_bytes)

        # The instructor notes TXT
        zf.writestr(result['txt_filename'], result['txt_content'])

        # The ElevenLabs snippet
        zf.writestr('elevenlabs-snippet.txt', result['elevenlabs_snippet'])

        # The Yola snippet
        zf.writestr('yola-snippet.txt', result['yola_snippet'])

        # The assembly checklist
        zf.writestr('assembly-checklist.md', result['checklist'])

    return zip_buffer.getvalue()
