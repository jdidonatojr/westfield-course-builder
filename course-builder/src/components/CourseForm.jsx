import React, { useState } from 'react'
import { extractSlideData, parseNotesFile, mergeNotes } from '../lib/pptxNotes'

function CourseForm({ onSubmit, errorMessage }) {
  const [courseNumber, setCourseNumber] = useState('')
  const [courseTitle, setCourseTitle] = useState('')
  const [courseType, setCourseType] = useState('')
  const [audience, setAudience] = useState('')
  const [sectionMap, setSectionMap] = useState('')
  const [teachingNotes, setTeachingNotes] = useState('')
  const [pptxFile, setPptxFile] = useState(null)
  const [slideData, setSlideData] = useState(null)
  const [rawSlideData, setRawSlideData] = useState(null)
  const [notesFile, setNotesFile] = useState(null)
  const [readingFile, setReadingFile] = useState(false)
  const [suggestingSection, setSuggestingSection] = useState(false)
  const [suggestingNotes, setSuggestingNotes] = useState(false)
  const [suggestError, setSuggestError] = useState('')
  const [notesStatus, setNotesStatus] = useState('')

  // Combine the parsed PPTX data with an optional notes file.
  // Returns the slideData to use, or throws on a count mismatch.
  const applyNotesIfPresent = (parsedPptx, notesArray) => {
    if (!notesArray) return parsedPptx
    return mergeNotes(parsedPptx, notesArray)
  }

  const handleFileChange = async (e) => {
    const file = e.target.files[0]
    if (!file) return

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

    // Read the file in the background so Suggest buttons work right away
    setReadingFile(true)
    setSlideData(null)
    setRawSlideData(null)
    setSuggestError('')
    try {
      const data = await extractSlideData(file)
      setRawSlideData(data)

      // If a notes file is already loaded, re-merge against the new pptx
      if (notesFile) {
        await loadAndApplyNotes(notesFile, data)
      } else {
        setSlideData(data)
      }
    } catch (err) {
      setSuggestError('Could not read the PowerPoint file.')
    } finally {
      setReadingFile(false)
    }
  }

  // Read a notes .txt file, parse it, and merge with the given pptx data.
  const loadAndApplyNotes = async (file, parsedPptx) => {
    setNotesStatus('')
    try {
      const text = await file.text()
      const notesArray = parseNotesFile(text)

      if (notesArray.length === 0) {
        setNotesStatus('error')
        setSuggestError(
          'Could not find any "Slide N:" sections in the notes file. ' +
          'Make sure it came from extractpptnotes.com.'
        )
        return
      }

      // This throws if counts don't match
      const merged = mergeNotes(parsedPptx, notesArray)
      setSlideData(merged)
      setNotesStatus('ok')
      setSuggestError('')
    } catch (err) {
      // Count mismatch or parse problem - reject and tell the user
      setNotesStatus('error')
      setSlideData(null)
      setSuggestError(err.message)
    }
  }

  const handleNotesFileChange = async (e) => {
    const file = e.target.files[0]
    if (!file) {
      // User cleared the notes file - revert to pptx-only notes
      setNotesFile(null)
      setNotesStatus('')
      if (rawSlideData) setSlideData(rawSlideData)
      return
    }
    setNotesFile(file)

    if (rawSlideData) {
      await loadAndApplyNotes(file, rawSlideData)
    }
    // If pptx isn't loaded yet, the merge happens when it finishes reading
  }

  const requestSuggestion = async (type) => {
    if (!slideData) {
      setSuggestError('Please upload a PowerPoint file first.')
      return
    }
    setSuggestError('')

    if (type === 'section_map') setSuggestingSection(true)
    else setSuggestingNotes(true)

    try {
      const response = await fetch('/api/suggest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          type: type,
          slide_data: slideData,
          course_title: courseTitle || pptxFile?.name || ''
        })
      })

      if (!response.ok) {
        const errorText = await response.text()
        throw new Error(errorText || 'Suggestion failed.')
      }

      const data = await response.json()
      if (type === 'section_map') {
        setSectionMap(data.suggestion)
      } else {
        setTeachingNotes(data.suggestion)
      }
    } catch (err) {
      setSuggestError(err.message)
    } finally {
      if (type === 'section_map') setSuggestingSection(false)
      else setSuggestingNotes(false)
    }
  }

  const handleSubmit = (e) => {
    e.preventDefault()

    const fields = {
      course_number: courseNumber,
      course_title: courseTitle,
      course_type: courseType,
      audience: audience,
      section_map: sectionMap,
      teaching_notes: teachingNotes
    }

    onSubmit(pptxFile, fields, slideData)
  }

  const isReady =
    pptxFile &&
    courseNumber &&
    courseTitle &&
    courseType &&
    audience &&
    sectionMap &&
    teachingNotes &&
    !readingFile

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

      {suggestError && (
        <div className="error-message">
          <strong>Suggestion error:</strong> {suggestError}
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
          <small className="hint">
            Selected: {pptxFile.name}
            {readingFile && ' · reading slides…'}
            {slideData && !readingFile && ` · ${slideData.totalSlides} slides ready`}
          </small>
        )}
      </div>

      {/* Optional speaker-notes file upload (for compressed decks) */}
      <div className="field">
        <label htmlFor="notes_file">
          Speaker notes file (.txt) — optional
        </label>
        <input
          type="file"
          id="notes_file"
          accept=".txt"
          onChange={handleNotesFileChange}
        />
        <small className="hint">
          Only needed if you compressed a large deck and the notes were lost.
          Upload the notes file from extractpptnotes.com. The slide count must
          match the PowerPoint exactly.
          {notesFile && notesStatus === 'ok' &&
            ` · ✓ notes matched and applied`}
          {notesFile && notesStatus === 'error' &&
            ` · ✗ see error above`}
        </small>
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
        <div className="label-row">
          <label htmlFor="section_map">Section map</label>
          <button
            type="button"
            className="suggest-button"
            onClick={() => requestSuggestion('section_map')}
            disabled={!slideData || suggestingSection}
          >
            {suggestingSection ? 'Thinking…' : '✨ Suggest from slides'}
          </button>
        </div>
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
        <div className="label-row">
          <label htmlFor="teaching_notes">Teaching notes</label>
          <button
            type="button"
            className="suggest-button"
            onClick={() => requestSuggestion('teaching_notes')}
            disabled={!slideData || suggestingNotes}
          >
            {suggestingNotes ? 'Thinking…' : '✨ Suggest from slides'}
          </button>
        </div>
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
