"""
AILA Course Builder — PDF streaming proxy

The browser calls this endpoint with a job_id. We look up the
CloudConvert PDF URL fresh (so it's not stale) and stream the bytes
straight back to the browser. Vercel does not buffer streaming
responses against the 4.5 MB limit, so any PDF size works.

POST /api/get_pdf
  JSON body: { "job_id": "..." }

Returns: application/pdf streamed bytes
"""

import os
import json
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler


CHUNK_SIZE = 64 * 1024  # 64 KB chunks


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            raw_body = self.rfile.read(content_length)
            payload = json.loads(raw_body.decode('utf-8'))

            job_id = payload.get('job_id', '').strip()
            if not job_id:
                self._send_error(400, 'job_id is required')
                return

            api_key = os.environ.get('CLOUDCONVERT_API_KEY', '')
            if not api_key:
                self._send_error(500, 'CloudConvert API key not configured.')
                return

            # Look up a fresh PDF URL right now (URLs can expire)
            pdf_url = get_fresh_pdf_url(job_id, api_key)

            # Open CloudConvert PDF stream
            pdf_req = urllib.request.Request(pdf_url)
            with urllib.request.urlopen(pdf_req, timeout=120) as pdf_response:
                # Send headers to the browser - streaming response (no Content-Length)
                self.send_response(200)
                self.send_header('Content-Type', 'application/pdf')
                self.send_header('Transfer-Encoding', 'chunked')
                self.end_headers()

                # Stream chunks straight through
                while True:
                    chunk = pdf_response.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    # Write chunk in HTTP chunked transfer-encoding format
                    chunk_header = f'{len(chunk):X}\r\n'.encode('ascii')
                    self.wfile.write(chunk_header)
                    self.wfile.write(chunk)
                    self.wfile.write(b'\r\n')

                # End of stream
                self.wfile.write(b'0\r\n\r\n')

        except Exception as e:
            # If we haven't sent headers yet, send error
            try:
                self._send_error(500, f'Server error: {str(e)}')
            except Exception:
                pass

    def _send_error(self, code, message):
        self.send_response(code)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(message.encode('utf-8'))


def get_fresh_pdf_url(job_id, api_key):
    """Query CloudConvert right now for the current download URL."""
    job_status_url = f'https://api.cloudconvert.com/v2/jobs/{job_id}'
    headers = {'Authorization': f'Bearer {api_key}'}

    req = urllib.request.Request(job_status_url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response:
        job_data = json.loads(response.read().decode('utf-8'))['data']

    for task in job_data['tasks']:
        if task['name'] == 'export-task' and task['status'] == 'finished':
            return task['result']['files'][0]['url']

    raise Exception('No finished export task found for this job.')
