"""
AILA Course Builder — Increment 2, read-only inspect test

What it does (READ ONLY — changes nothing):
  1. Logs in to ElevenLabs with the Westfield key.
  2. Reads the recommender agent's current settings.
  3. Shows its knowledge-base list and EXACTLY where that list lives
     inside the agent's settings, so we know how to add to it safely later.

How to test in a browser:
  https://aila-course-files.vercel.app/api/test_inspect_agent
  (optional: ?agent_id=... to look at a different agent)

Returns JSON: { ok, agent_id, agent_name, found, message }
"""

import os
import json
import urllib.parse
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler

# Default = the TEST recommender (Learning Path) agent.
DEFAULT_AGENT_ID = 'agent_2201kthka4h3fddvtxj1sz9q4be8'
EL_AGENT_URL = 'https://api.elevenlabs.io/v1/convai/agents/'


def find_knowledge_base(obj, path=''):
    """
    Walk through the agent settings and report every place a
    'knowledge_base' list appears, along with the path to reach it.
    Returns a list of { path, entries }.
    """
    hits = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            here = f'{path}.{key}' if path else key
            if key == 'knowledge_base':
                hits.append({'path': here, 'entries': value})
            hits.extend(find_knowledge_base(value, here))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            here = f'{path}[{i}]'
            hits.extend(find_knowledge_base(item, here))
    return hits


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            key = os.environ.get('ELEVENLABS_API_KEY', '').strip()
            if not key:
                return self._send(500, {'ok': False,
                    'message': 'ELEVENLABS_API_KEY is not set on this project.'})

            query = urllib.parse.urlparse(self.path).query
            params = urllib.parse.parse_qs(query)
            agent_id = params.get('agent_id', [DEFAULT_AGENT_ID])[0].strip()

            # Read the agent (GET = read only).
            url = EL_AGENT_URL + urllib.parse.quote(agent_id)
            req = urllib.request.Request(url, method='GET')
            req.add_header('xi-api-key', key)
            with urllib.request.urlopen(req, timeout=60) as resp:
                agent = json.loads(resp.read().decode('utf-8'))

            agent_name = agent.get('name', '(no name field)')

            # Find where the knowledge_base list lives, and what's in it.
            hits = find_knowledge_base(agent)

            # Also show the top-level setting groups, to help us navigate.
            top_level_keys = list(agent.keys())
            cc = agent.get('conversation_config', {})
            cc_keys = list(cc.keys()) if isinstance(cc, dict) else []

            return self._send(200, {
                'ok': True,
                'agent_id': agent_id,
                'agent_name': agent_name,
                'found': hits,                     # path(s) + current documents
                'top_level_keys': top_level_keys,
                'conversation_config_keys': cc_keys,
                'message': 'Read-only inspection complete. Nothing was changed.'
            })

        except urllib.error.HTTPError as e:
            detail = ''
            try:
                detail = e.read().decode('utf-8', errors='replace')[:300]
            except Exception:
                pass
            return self._send(502, {'ok': False,
                'message': f'ElevenLabs API error ({e.code}): {detail}'})
        except Exception as e:
            return self._send(500, {'ok': False,
                'message': f'Server error: {str(e)}'})

    def _send(self, code, obj):
        body = json.dumps(obj, indent=2, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
