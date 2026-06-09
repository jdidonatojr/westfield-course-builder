"""
Read-only inspector for the TEACHER agent (changes nothing).

Shows:
  - agent name
  - knowledge-base documents (names + count)
  - the keys inside the prompt object
  - whether the prompt has a "# COURSE MENU" (or similar course list)
  - a bounded excerpt of the prompt so we can see how it is organized

How to test:
  https://aila-course-files.vercel.app/api/test_inspect_teacher
  (optional ?agent_id=...)
"""

import os
import json
import urllib.parse
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler

DEFAULT_AGENT_ID = 'agent_5701kth9zyb9e90rcm2w0rrc5f8n'   # Teacher agent
EL_AGENT_URL = 'https://api.elevenlabs.io/v1/convai/agents/'


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            key = os.environ.get('ELEVENLABS_API_KEY', '').strip()
            if not key:
                return self._send(500, {'ok': False, 'message': 'ELEVENLABS_API_KEY not set.'})

            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            agent_id = q.get('agent_id', [DEFAULT_AGENT_ID])[0].strip()

            req = urllib.request.Request(EL_AGENT_URL + urllib.parse.quote(agent_id), method='GET')
            req.add_header('xi-api-key', key)
            with urllib.request.urlopen(req, timeout=60) as resp:
                agent = json.loads(resp.read().decode('utf-8'))

            cc = agent.get('conversation_config', {})
            prompt_obj = cc.get('agent', {}).get('prompt', {})
            prompt_text = prompt_obj.get('prompt', '') or ''
            kb = prompt_obj.get('knowledge_base', [])
            kb_names = [d.get('name') for d in kb if isinstance(d, dict)] if isinstance(kb, list) else []

            # Bounded prompt excerpt (so we never dump a huge prompt).
            excerpt = prompt_text[:1800]

            return self._send(200, {
                'ok': True,
                'agent_name': agent.get('name'),
                'kb_count': len(kb_names),
                'kb_names': kb_names,
                'prompt_obj_keys': list(prompt_obj.keys()) if isinstance(prompt_obj, dict) else [],
                'prompt_length': len(prompt_text),
                'has_course_menu_heading': '# COURSE MENU' in prompt_text,
                'mentions_pdf': 'pdf' in prompt_text.lower(),
                'mentions_notes': 'note' in prompt_text.lower(),
                'prompt_excerpt': excerpt,
                'message': 'Read-only. Nothing was changed.'
            })

        except urllib.error.HTTPError as e:
            detail = ''
            try:
                detail = e.read().decode('utf-8', errors='replace')[:300]
            except Exception:
                pass
            return self._send(502, {'ok': False, 'message': f'ElevenLabs API error ({e.code}): {detail}'})
        except Exception as e:
            return self._send(500, {'ok': False, 'message': f'Server error: {str(e)}'})

    def _send(self, code, obj):
        body = json.dumps(obj, indent=2, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
