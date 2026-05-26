"""
AILA Course Builder — Health check endpoint

A simple endpoint to confirm the backend is alive and the Python
runtime is working. Visit /api/health after deployment to test.
"""

from http.server import BaseHTTPRequestHandler
import json


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()

        response = {
            'status': 'ok',
            'service': 'AILA Course Builder',
            'version': '0.1.0',
            'message': 'Backend is alive'
        }

        self.wfile.write(json.dumps(response).encode('utf-8'))
