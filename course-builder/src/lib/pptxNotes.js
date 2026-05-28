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

/**
 * Parse a speaker-notes .txt file in the extractpptnotes.com format.
 *
 * The format looks like:
 *   Slide 1:
 *   ----------------------------------------
 *   (notes text, possibly multiple paragraphs)
 *
 *   Slide 2:
 *   ----------------------------------------
 *   (notes text)
 *
 * @param {string} text - The full text content of the .txt file
 * @returns {Array<string>} Array of notes strings, indexed by slide order
 */
export function parseNotesFile(text) {
  // Normalize line endings
  const normalized = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n')

  // Split on "Slide N:" markers. The capturing group keeps the slide number.
  // We use a regex that finds each "Slide N:" header at the start of a line.
  const parts = normalized.split(/^Slide\s+(\d+):\s*$/m)

  // parts looks like: ["", "1", "<notes>", "2", "<notes>", ...]
  // Element 0 is whatever came before the first "Slide 1:" (usually blank).
  const notesBySlide = {}
  for (let i = 1; i < parts.length; i += 2) {
    const slideNum = parseInt(parts[i], 10)
    let noteBlock = parts[i + 1] || ''

    // Remove a leading divider line of dashes (with optional surrounding
    // whitespace/newlines). The export tool puts a row of dashes right
    // after each "Slide N:" header.
    noteBlock = noteBlock.replace(/^\s*-{3,}\s*\n?/, '')

    // Trim surrounding whitespace
    noteBlock = noteBlock.trim()

    // A lone dash or empty divider remnant means "no notes"
    if (/^-*$/.test(noteBlock)) {
      noteBlock = ''
    }

    notesBySlide[slideNum] = noteBlock
  }

  // Convert to an ordered array (slide 1 -> index 0)
  const slideNums = Object.keys(notesBySlide)
    .map(n => parseInt(n, 10))
    .sort((a, b) => a - b)

  const orderedNotes = []
  for (const num of slideNums) {
    orderedNotes.push(notesBySlide[num])
  }

  return orderedNotes
}

/**
 * Merge externally-supplied notes into slide data.
 *
 * Used when the user uploads a compressed .pptx (notes stripped) plus a
 * separate notes .txt file. The visible content comes from the .pptx;
 * the notes come from the .txt.
 *
 * STRICT: if the counts don't match, this throws an error. A mismatch
 * would misalign the ElevenLabs widget, so we reject rather than guess.
 *
 * @param {Object} slideData - Result of extractSlideData()
 * @param {Array<string>} notesArray - Result of parseNotesFile()
 * @returns {Object} New slideData with notes overlaid
 */
export function mergeNotes(slideData, notesArray) {
  const slideCount = slideData.slides.length
  const notesCount = notesArray.length

  if (slideCount !== notesCount) {
    throw new Error(
      `Slide count mismatch: the PowerPoint has ${slideCount} slides, ` +
      `but the notes file has ${notesCount} slides. ` +
      `These must match exactly. If your original deck had hidden slides, ` +
      `remove them before extracting notes, then try again.`
    )
  }

  const mergedSlides = slideData.slides.map((slide, i) => ({
    visible: slide.visible,
    notes: notesArray[i],
    hidden: slide.hidden
  }))

  return {
    slides: mergedSlides,
    totalSlides: slideData.totalSlides,
    hiddenCount: slideData.hiddenCount
  }
}
