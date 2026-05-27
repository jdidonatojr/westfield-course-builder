import React, { useState } from 'react'

function CourseForm({ onSubmit, errorMessage }) {
  const [courseNumber, setCourseNumber] = useState('')
  const [courseTitle, setCourseTitle] = useState('')
  const [courseType, setCourseType] = useState('')
  const [audience, setAudience] = useState('')
  const [sectionMap, setSectionMap] = useState('')
  const [teachingNotes, setTeachingNotes] = useState('')
  const [pptxFile, setPptxFile] = useState(null)

  const handleFileChange = (e) => {
    const file = e.target.files[0]
    if (file) {
      // Auto-fill the course title from the filename if it's empty
      if (!courseTitle) {
        const guessedTitle = file.name
          .replace(/\.pptx$/i, '')
          .replace(/^\[?(Presentation|Handout)\]?\s*/i, '')
          .replace(/[_-]+/g, ' ')
          .trim()
        setCourseTitle(guessedTitle)
      }
      setPptxFile(file)
    }
  }

  const handleSubmit = (e) => {
    e.preventDefault()

    // Pass the file and field values up to the parent component
    const fields = {
      course_number: courseNumber,
      course_title: courseTitle,
      course_type: courseType,
      audience: audience,
      section_map: sectionMap,
      teaching_notes: teachingNotes
    }

    onSubmit(pptxFile, fields)
  }

  const isReady =
    pptxFile &&
    courseNumber &&
    courseTitle &&
    courseType &&
    audience &&
    sectionMap &&
    teachingNotes

  return (
    <form onSubmit={handleSubmit} className="card">
      <h2>Add a Course</h2>
      <p className="form-intro">
        Fill in the details below and upload your PowerPoint deck. The tool
        will return a ZIP with everything you need to publish the course.
      </p>

      {errorMessage && (
        <div className="error-message">
          <strong>Something went wrong:</strong> {errorMessage}
        </div>
      )}

      {/* PPTX file upload */}
      <div className="field">
        <label htmlFor="pptx">PowerPoint file (.pptx)</label>
        <input
          type="file"
          id="pptx"
          accept=".pptx"
          onChange={handleFileChange}
          required
        />
        {pptxFile && (
          <small className="hint">Selected: {pptxFile.name}</small>
        )}
      </div>

      {/* Course number */}
      <div className="field">
        <label htmlFor="course_number">Course number</label>
        <input
          type="number"
          id="course_number"
          min="1"
          placeholder="e.g., 5"
          value={courseNumber}
          onChange={(e) => setCourseNumber(e.target.value)}
          required
        />
        <small className="hint">
          The next number in your sequence. Once assigned, don't reuse it.
        </small>
      </div>

      {/* Course title */}
      <div className="field">
        <label htmlFor="course_title">Course title</label>
        <input
          type="text"
          id="course_title"
          placeholder="e.g., Ace Your Next Job Interview"
          value={courseTitle}
          onChange={(e) => setCourseTitle(e.target.value)}
          required
        />
        <small className="hint">
          The full title as it appears on slide 1.
        </small>
      </div>

      {/* Course type */}
      <div className="field">
        <label htmlFor="course_type">Course type</label>
        <input
          type="text"
          id="course_type"
          placeholder="e.g., Skills-based, hands-on"
          value={courseType}
          onChange={(e) => setCourseType(e.target.value)}
          required
        />
      </div>

      {/* Audience */}
      <div className="field">
        <label htmlFor="audience">Audience</label>
        <input
          type="text"
          id="audience"
          placeholder="e.g., Job seekers preparing for interviews"
          value={audience}
          onChange={(e) => setAudience(e.target.value)}
          required
        />
      </div>

      {/* Section map */}
      <div className="field">
        <label htmlFor="section_map">Section map</label>
        <textarea
          id="section_map"
          rows="7"
          placeholder={`One section per line, like:
Introduction (slides 1-4)
Prepare (slides 5-17)
Practice (slides 18-21)
Recap (slides 22-25)`}
          value={sectionMap}
          onChange={(e) => setSectionMap(e.target.value)}
          required
        />
        <small className="hint">
          One section per line. Include the slide range in parentheses.
        </small>
      </div>

      {/* Teaching notes */}
      <div className="field">
        <label htmlFor="teaching_notes">Teaching notes</label>
        <textarea
          id="teaching_notes"
          rows="6"
          placeholder={`One bullet per line, like:
This is a Grow with Google partner course
Keep coming back to the "3 P's" framework
Slide 12 is key — slow down here`}
          value={teachingNotes}
          onChange={(e) => setTeachingNotes(e.target.value)}
          required
        />
        <small className="hint">
          One short bullet per line. These guide the AI agent.
        </small>
      </div>

      <button
        type="submit"
        className="primary-button"
        disabled={!isReady}
      >
        Generate Course Package
      </button>
    </form>
  )
}

export default CourseForm
