"""
AILA PDF Course Builder — /api/build

Generates the ElevenLabs snippet, the Yola snippet, and the assembly
checklist from the form fields the browser sends. No PowerPoint, no
CloudConvert, no PDF streaming — so the response is always small text
and the 4.5 MB function-response limit can never be hit.

POST /api/build
  JSON body:
    {
      "total_slides": 44,
      "fields": {
        "course_number": "...",
        "course_title": "...",
        "course_type": "...",
        "audience": "...",
        "section_map": "...multi-line...",
        "teaching_notes": "...multi-line..."
      }
    }

Returns: JSON
    {
      "pdf_filename": "...",
      "txt_filename": "...",
      "elevenlabs_snippet": "...",
      "yola_snippet": "...",
      "checklist": "...",
      "filename_base": "..."
    }
"""

import os
import sys
import json
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '_lib'))
from processor import (
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

            fields = payload.get('fields')
            if not fields:
                self._send_error(400, 'Missing required field: fields')
                return

            try:
                total_slides = int(payload.get('total_slides'))
            except (TypeError, ValueError):
                self._send_error(400, 'total_slides must be a number (the PDF page count).')
                return

            required = [
                'course_number', 'course_title', 'course_type',
                'audience', 'section_map', 'teaching_notes'
            ]
            for f in required:
                if not str(fields.get(f, '')).strip():
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

            filename_base = make_filename(course_info['course_title'])
            pdf_filename = f"{filename_base}.pdf"
            txt_filename = f"{filename_base}.txt"

            elevenlabs_snippet = build_elevenlabs_snippet(
                course_info, total_slides, pdf_filename, txt_filename
            )
            yola_snippet = build_yola_snippet(
                course_info, total_slides, pdf_filename
            )
            checklist = build_checklist(
                course_info, pdf_filename, txt_filename
            )

            response_payload = {
                'pdf_filename': pdf_filename,
                'txt_filename': txt_filename,
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
