import React, { useState } from 'react'
import CourseForm from './components/CourseForm'
import ResultPanel from './components/ResultPanel'

function App() {
  // Three possible states:
  //   'form'      - showing the upload form
  //   'working'   - processing the upload
  //   'done'      - showing the result with download
  const [stage, setStage] = useState('form')
  const [result, setResult] = useState(null)
  const [errorMessage, setErrorMessage] = useState('')

  // Called when the user submits the form
  const handleSubmit = async (formData) => {
    setStage('working')
    setErrorMessage('')

    try {
      const response = await fetch('/api/process', {
        method: 'POST',
        body: formData  // multipart form data with the .pptx and fields
      })

      if (!response.ok) {
        const errorText = await response.text()
        throw new Error(errorText || 'Something went wrong on the server.')
      }

      // The response is the ZIP file itself
      const blob = await response.blob()
      const downloadUrl = URL.createObjectURL(blob)

      setResult({ downloadUrl })
      setStage('done')
    } catch (err) {
      setErrorMessage(err.message)
      setStage('form')
    }
  }

  // Called when the user wants to start over
  const handleReset = () => {
    if (result?.downloadUrl) {
      URL.revokeObjectURL(result.downloadUrl)
    }
    setResult(null)
    setStage('form')
    setErrorMessage('')
  }

  return (
    <div className="container">
      <header>
        <h1>AILA Course Builder</h1>
        <p className="subtitle">
          Turn a PowerPoint deck into a complete course package
        </p>
      </header>

      <main>
        {stage === 'form' && (
          <CourseForm
            onSubmit={handleSubmit}
            errorMessage={errorMessage}
          />
        )}

        {stage === 'working' && (
          <div className="card">
            <h2>Processing your deck…</h2>
            <p>
              Reading the slides, extracting notes, converting to PDF, and
              building the package. This usually takes 30 seconds.
            </p>
          </div>
        )}

        {stage === 'done' && (
          <ResultPanel
            downloadUrl={result.downloadUrl}
            onReset={handleReset}
          />
        )}
      </main>

      <footer>
        <p>AI Learning Alliance · v0.1.0</p>
      </footer>
    </div>
  )
}

export default App
