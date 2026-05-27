import React, { useState } from 'react'
import CourseForm from './components/CourseForm'
import ResultPanel from './components/ResultPanel'
import { extractSlideData } from './lib/pptxNotes'

function App() {
  // Stages: 'form' | 'reading' | 'creating_job' | 'uploading' | 'converting' | 'done'
  const [stage, setStage] = useState('form')
  const [statusMessage, setStatusMessage] = useState('')
  const [result, setResult] = useState(null)
  const [errorMessage, setErrorMessage] = useState('')

  const handleSubmit = async (pptxFile, fields, preparsedSlideData) => {
    setErrorMessage('')

    try {
      // ----- Step 1: parse the .pptx if not already done -----
      let slideData = preparsedSlideData
      if (!slideData) {
        setStage('reading')
        setStatusMessage('Reading your slides…')
        slideData = await extractSlideData(pptxFile)
      }

      // ----- Step 2: ask backend for a CloudConvert upload URL -----
      setStage('creating_job')
      setStatusMessage('Preparing upload…')

      const jobResponse = await fetch('/api/create_job', { method: 'POST' })
      if (!jobResponse.ok) {
        const errorText = await jobResponse.text()
        throw new Error(errorText || 'Could not start the upload.')
      }
      const jobInfo = await jobResponse.json()

      // ----- Step 3: upload directly to CloudConvert -----
      setStage('uploading')
      setStatusMessage('Uploading your PowerPoint…')

      const cloudFormData = new FormData()
      Object.entries(jobInfo.upload_parameters).forEach(([key, value]) => {
        cloudFormData.append(key, value)
      })
      cloudFormData.append('file', pptxFile)

      const uploadResponse = await fetch(jobInfo.upload_url, {
        method: 'POST',
        body: cloudFormData
      })
      if (!uploadResponse.ok) {
        throw new Error('Upload to CloudConvert failed.')
      }

      // ----- Step 4: send slide data + form fields to backend, get ZIP -----
      setStage('converting')
      setStatusMessage('Converting slides to PDF and building your package…')

      const processPayload = {
        job_id: jobInfo.job_id,
        slide_data: slideData,
        fields: fields
      }

      const processResponse = await fetch('/api/process', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(processPayload)
      })
      if (!processResponse.ok) {
        const errorText = await processResponse.text()
        throw new Error(errorText || 'Processing failed.')
      }

      const blob = await processResponse.blob()
      const downloadUrl = URL.createObjectURL(blob)

      setResult({ downloadUrl })
      setStage('done')
    } catch (err) {
      setErrorMessage(err.message)
      setStage('form')
    }
  }

  const handleReset = () => {
    if (result?.downloadUrl) {
      URL.revokeObjectURL(result.downloadUrl)
    }
    setResult(null)
    setStage('form')
    setErrorMessage('')
    setStatusMessage('')
  }

  const workingStages = ['reading', 'creating_job', 'uploading', 'converting']

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

        {workingStages.includes(stage) && (
          <div className="card">
            <h2>{statusMessage}</h2>
            <p>
              This can take up to a minute for large decks. Please don't close
              this tab.
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
        <p>AI Learning Alliance · v0.3.0</p>
      </footer>
    </div>
  )
}

export default App
