"""
AILA Course Builder — Suggestion endpoint

Calls Claude API to generate a suggested Section Map or Teaching Notes
based on the slide content the browser has already parsed.

POST /api/suggest
  JSON body:
    {
      "type": "section_map" | "teaching_notes",
      "slide_data": { "slides": [{ "visible": "...", "notes": "..." }, ...] },
      "course_title": "..."
    }

Returns: JSON { "suggestion": "..." }
"""

import os
import json
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler


# ============================================================
# Prompts for each suggestion type
# ============================================================
SECTION_MAP_PROMPT = """You are helping organize a slide deck into logical sections.

The course is titled: "{course_title}"
It has {total_slides} visible slides.

Here are the slide titles and brief content for each slide:

{slide_summary}

Generate a Section Map that groups these slides into 4-8 logical sections.

Output rules:
- ONE section per line, no blank lines, no commentary
- Format each line exactly as: SectionName (slides X-Y)
- The first section should cover the opening/introduction slides
- The last section should cover the closing/recap/resources slides
- Use short, clear section names (2-5 words)
- Cover ALL slides from 1 to {total_slides} with no gaps or overlaps

Example output format:
Introduction (slides 1-4)
Foundations (slides 5-12)
Practice (slides 13-20)
Recap and Resources (slides 21-25)

Now write the Section Map for this course. Output ONLY the section lines, nothing else."""


TEACHING_NOTES_PROMPT = """You are helping write teaching tips for an AI agent that will teach this course to learners.

The course is titled: "{course_title}"
It has {total_slides} visible slides.

Here are the slide titles and brief content for each slide:

{slide_summary}

Generate 4-6 short Teaching Notes bullets that will help the AI agent teach this course well.

Good teaching notes are:
- High-level guidance about tone, pace, or emphasis (not slide-by-slide instructions)
- Specific to THIS course's actual content and audience
- Practical and actionable
- One short sentence each

Examples of good teaching notes:
- This course is built around the "3 P's" framework: keep referring back to it
- Many learners may feel nervous about this topic — open with reassurance
- Slide 12 is the most important slide — slow down and invite practice
- The role-play scenarios are the heart of the course — don't rush them

Output rules:
- ONE bullet per line
- No bullet markers (no dashes, no asterisks) — just the text
- No blank lines, no commentary, no introduction
- 4-6 bullets total

Now write the Teaching Notes for this course. Output ONLY the bullets, nothing else."""


# ============================================================
# Build a compact summary of slides for the prompt
# ============================================================
def build_slide_summary(slides, max_visible=200, max_notes=600):
    """
    Create a short summary of each slide for the AI prompt.

    Includes BOTH the visible slide text AND the instructor notes, because
    on many decks the real teaching substance lives in the notes (not on the
    slide). Length is capped per slide so the prompt does not get huge.
    """
    lines = []
    for i, slide in enumerate(slides, 1):
        visible = (slide.get('visible') or '').strip().replace('\n', ' ')
        if len(visible) > max_visible:
            visible = visible[:max_visible] + '...'
        if not visible:
            visible = '(no visible text)'

        notes = (slide.get('notes') or '').strip().replace('\n', ' ')
        if len(notes) > max_notes:
            notes = notes[:max_notes] + '...'

        if notes:
            lines.append(f"Slide {i}: {visible}\n    Instructor notes: {notes}")
        else:
            lines.append(f"Slide {i}: {visible}")
    return '\n'.join(lines)


# ============================================================
# Call the Claude API
# ============================================================
def call_claude(prompt, api_key):
    """Send a single-message prompt to Claude and return the text response."""
    payload = {
        'model': 'claude-haiku-4-5-20251001',
        'max_tokens': 1024,
        'messages': [{'role': 'user', 'content': prompt}]
    }

    req = urllib.request.Request(
        'https://api.anthropic.com/v1/messages',
        data=json.dumps(payload).encode('utf-8'),
        headers={
            'x-api-key': api_key,
            'anthropic-version': '2023-06-01',
            'content-type': 'application/json'
        },
        method='POST'
    )

    with urllib.request.urlopen(req, timeout=30) as response:
        result = json.loads(response.read().decode('utf-8'))

    for block in result.get('content', []):
        if block.get('type') == 'text':
            return block['text'].strip()

    return ''


# ============================================================
# HANDLER
# ============================================================
class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            raw_body = self.rfile.read(content_length)
            payload = json.loads(raw_body.decode('utf-8'))

            suggest_type = payload.get('type', '')
            if suggest_type not in ('section_map', 'teaching_notes'):
                self._send_error(400, 'type must be "section_map" or "teaching_notes"')
                return

            slide_data = payload.get('slide_data', {})
            slides = slide_data.get('slides', [])
            if not slides:
                self._send_error(400, 'slide_data.slides is required and must not be empty')
                return

            course_title = payload.get('course_title', '').strip() or 'Untitled Course'

            api_key = os.environ.get('ANTHROPIC_API_KEY', '').strip()
            if not api_key:
                self._send_error(500, 'ANTHROPIC_API_KEY not configured on the server.')
                return

            slide_summary = build_slide_summary(slides)
            template = SECTION_MAP_PROMPT if suggest_type == 'section_map' else TEACHING_NOTES_PROMPT
            prompt = template.format(
                course_title=course_title,
                total_slides=len(slides),
                slide_summary=slide_summary
            )

            suggestion = call_claude(prompt, api_key)

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'suggestion': suggestion}).encode('utf-8'))

        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8', errors='replace')
            self._send_error(500, f'Claude API error ({e.code}): {error_body[:300]}')
        except Exception as e:
            self._send_error(500, f'Server error: {str(e)}')

    def _send_error(self, code, message):
        self.send_response(code)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(message.encode('utf-8'))
