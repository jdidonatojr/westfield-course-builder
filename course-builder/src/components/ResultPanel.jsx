import React from 'react'

function ResultPanel({ downloadUrl, onReset }) {
  return (
    <div className="card">
      <h2>✅ Course package ready</h2>
      <p>
        Your ZIP file contains everything you need to publish the course.
        Click the button below to download it.
      </p>

      <a
        href={downloadUrl}
        download="course-package.zip"
        className="primary-button download-link"
      >
        Download ZIP
      </a>

      <h3 className="next-steps-heading">What's inside</h3>
      <ul className="next-steps">
        <li><strong>Course-Name.pdf</strong> — slide deck for GitHub and ElevenLabs</li>
        <li><strong>Course-Name.txt</strong> — instructor notes for the agent</li>
        <li><strong>elevenlabs-snippet.txt</strong> — paste into ElevenLabs system prompt</li>
        <li><strong>yola-snippet.txt</strong> — paste into Yola page code</li>
        <li><strong>assembly-checklist.txt</strong> — step-by-step instructions</li>
      </ul>

      <p className="next-steps-tip">
        Open <strong>assembly-checklist.txt</strong> first — it walks you through
        exactly where each file goes.
      </p>

      <button onClick={onReset} className="secondary-button">
        Process Another Course
      </button>
    </div>
  )
}

export default ResultPanel
