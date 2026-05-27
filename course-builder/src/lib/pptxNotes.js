/**
 * Browser-side .pptx parser
 *
 * A .pptx file is just a ZIP containing XML files. This module reads the
 * file in the browser, extracts the visible text and speaker notes for
 * each slide, and detects hidden slides — all without sending the file
 * to any server.
 */

import JSZip from 'jszip'

/**
 * Parse a .pptx File object and return slide data.
 *
 * @param {File} pptxFile - The .pptx file from the file input
 * @returns {Promise<Object>} { slides: [{visible, notes, hidden}], totalSlides }
 */
export async function extractSlideData(pptxFile) {
  const arrayBuffer = await pptxFile.arrayBuffer()
  const zip = await JSZip.loadAsync(arrayBuffer)

  // Find all slide files (ppt/slides/slide1.xml, slide2.xml, etc.)
  const slideFiles = []
  zip.forEach((path, file) => {
    const match = path.match(/^ppt\/slides\/slide(\d+)\.xml$/)
    if (match) {
      slideFiles.push({ path, num: parseInt(match[1], 10), file })
    }
  })
  // Sort numerically so slide2 comes before slide10
  slideFiles.sort((a, b) => a.num - b.num)

  const slides = []

  for (const slideFile of slideFiles) {
    const slideXml = await slideFile.file.async('string')

    // Check if slide is hidden (show="0" attribute)
    const hidden = /<p:sld[^>]*show="0"/.test(slideXml)

    // Extract visible text from <a:t> elements
    const visibleText = extractTextFromXml(slideXml)

    // Find the matching notes file (e.g., ppt/notesSlides/notesSlide5.xml)
    let notesText = ''
    const notesPath = `ppt/notesSlides/notesSlide${slideFile.num}.xml`
    const notesFile = zip.file(notesPath)
    if (notesFile) {
      const notesXml = await notesFile.async('string')
      notesText = extractTextFromXml(notesXml)
    }

    slides.push({
      visible: visibleText,
      notes: notesText,
      hidden: hidden
    })
  }

  // Filter out hidden slides and renumber
  const visibleSlides = slides.filter(s => !s.hidden)

  return {
    slides: visibleSlides,
    totalSlides: visibleSlides.length,
    hiddenCount: slides.length - visibleSlides.length
  }
}

/**
 * Pull text from <a:t>...</a:t> elements in the XML.
 * Joins them in order, treating paragraph breaks as newlines.
 */
function extractTextFromXml(xml) {
  const lines = []
  // Split on paragraph elements to preserve line breaks
  const paragraphs = xml.split(/<a:p[ >]/)
  for (const para of paragraphs) {
    // Get all <a:t> text runs within this paragraph
    const textRuns = []
    const regex = /<a:t[^>]*>([\s\S]*?)<\/a:t>/g
    let match
    while ((match = regex.exec(para)) !== null) {
      // Decode common XML entities
      const text = match[1]
        .replace(/&amp;/g, '&')
        .replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>')
        .replace(/&quot;/g, '"')
        .replace(/&#39;/g, "'")
        .replace(/&apos;/g, "'")
      textRuns.push(text)
    }
    if (textRuns.length > 0) {
      lines.push(textRuns.join(''))
    }
  }
  return lines.join('\n').trim()
}
