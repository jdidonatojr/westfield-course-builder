"""
AILA Course Builder — Step 1 of 2-step upload flow

Creates a CloudConvert job and returns the direct-upload URL to the browser.
The browser will upload the .pptx directly to CloudConvert (bypassing Vercel's
4.5 MB function payload limit).

POST /api/create_job
  body: {} (no body needed)

Returns: JSON with job_id and upload form details
"""

import os
import json
from http.server import BaseHTTPRequestHandler
import urllib.request
import urllib.error


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            api_key = os.environ.get('CLOUDCONVERT_API_KEY', '')
            if not api_key:
                self._send_error(500, 'CloudConvert API key not configured.')
                return

            # Build the job: upload → convert → export-url
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

            # POST to CloudConvert to create the job
            req = urllib.request.Request(
                'https://api.cloudconvert.com/v2/jobs',
                data=json.dumps(job_payload).encode('utf-8'),
                headers={
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json'
                },
                method='POST'
            )

            with urllib.request.urlopen(req, timeout=30) as response:
                job_data = json.loads(response.read().decode('utf-8'))['data']

            # Find the upload task and pull out its form URL/parameters
            upload_task = None
            for task in job_data['tasks']:
                if task['name'] == 'upload-task':
                    upload_task = task
                    break

            if not upload_task or not upload_task.get('result'):
                self._send_error(500, 'CloudConvert did not return upload form.')
                return

            # Send back what the browser needs to upload directly
            response_payload = {
                'job_id': job_data['id'],
                'upload_url': upload_task['result']['form']['url'],
                'upload_parameters': upload_task['result']['form']['parameters']
            }

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(response_payload).encode('utf-8'))

        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8', errors='replace')
            self._send_error(
                500,
                f'CloudConvert error ({e.code}): {error_body[:300]}'
            )
        except Exception as e:
            self._send_error(500, f'Server error: {str(e)}')

    def _send_error(self, code, message):
        self.send_response(code)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(message.encode('utf-8'))
