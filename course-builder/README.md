# Westfield Course Builder

A web tool that turns a PowerPoint deck into everything needed to publish a new course in the AI Learning Alliance platform.

## What it does

You upload one `.pptx` file. The tool gives you back a ZIP package containing:

- `Course-Name.pdf` — the slide deck as a PDF (for GitHub and ElevenLabs)
- `Course-Name.txt` — instructor notes for the AI agent (for ElevenLabs)
- `elevenlabs-snippet.txt` — code block to paste into the ElevenLabs system prompt
- `yola-snippet.txt` — code block to paste into the Yola page
- `assembly-checklist.md` — step-by-step instructions for assembly
- `qr-code.png` — optional, if a handout URL is provided

## Workflows

1. **Add a course** — upload a new .pptx, get the ZIP
2. **Update a course** — same as Add, using an existing course number
3. **Delete a course** — get a removal checklist (no .pptx needed)

## How it works (technical)

- **Frontend:** React, hosted on Vercel
- **Backend:** Python serverless functions on Vercel
- **PDF conversion:** CloudConvert API
- **Storage:** None (the tool is stateless)

## Project structure

```
/course-builder/
  /api/                Python serverless functions
  /public/             Static assets
  /src/                React app source
    /components/       UI components
    /lib/              Helper functions
  package.json         Frontend dependencies
  requirements.txt     Python dependencies
  vercel.json          Vercel deployment config
  README.md            This file
```

## Setup

(Setup instructions will be added once development is complete.)

## Status

🚧 Phase 1 — under construction
