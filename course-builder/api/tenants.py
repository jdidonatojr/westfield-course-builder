"""GET /api/tenants — list the available tenant (customer) names.

Returns ONLY safe display fields: name, label, player_base.
NEVER returns keys, tokens, or agent IDs. The server keeps those.
If TENANTS_JSON is not set, returns an empty list (the form then
behaves exactly as it did before multi-tenancy).
"""

import os
import json
from http.server import BaseHTTPRequestHandler


class handler(BaseHTTPRequestHandler):

    def do_GET(self):
        tenants = []
        raw = os.environ.get('TENANTS_JSON', '').strip()
        if raw:
            try:
                data = json.loads(raw)
                if isinstance(data, dict):
                    for name in sorted(data.keys()):
                        card = data.get(name)
                        if isinstance(card, dict):
                            tenants.append({
                                'name': name,
                                'label': str(card.get('label', '') or name),
                                'player_base': str(card.get('player_base', '') or ''),
                            })
            except Exception:
                # Broken JSON: return an empty list here; publish_course
                # reports the precise error if a tenant is actually chosen.
                tenants = []

        body = json.dumps({'tenants': tenants}).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
