import { useEffect, useState } from 'react'

import { api, describeError } from '../api'

interface Props {
  path: string
  title: string
}

export function PdfPreview({ path, title }: Props) {
  const [objectUrl, setObjectUrl] = useState<string | null>(null)
  const [problem, setProblem] = useState<string | null>(null)

  useEffect(() => {
    let current: string | null = null
    let cancelled = false
    setObjectUrl(null)
    setProblem(null)

    api
      .fileUrl(path)
      .then((url) => {
        if (cancelled) {
          URL.revokeObjectURL(url)
          return
        }
        current = url
        setObjectUrl(url)
      })
      .catch((error: unknown) => {
        if (!cancelled) setProblem(describeError(error))
      })

    // An object URL pins the whole PDF in memory until it is revoked.
    return () => {
      cancelled = true
      if (current) URL.revokeObjectURL(current)
    }
  }, [path])

  return (
    <section className="card preview">
      <header>
        <h2>{title}</h2>
        {objectUrl && (
          <span className="actions">
            <a href={objectUrl} target="_blank" rel="noreferrer">
              Open in a tab
            </a>
            <a href={objectUrl} download={`${title}.pdf`}>
              Download
            </a>
          </span>
        )}
      </header>

      {problem && (
        <p className="failure">
          Could not load the PDF: {problem}. It is still on the server; the file list below links
          to it directly.
        </p>
      )}
      {!objectUrl && !problem && <p className="hint">Loading the PDF…</p>}
      {objectUrl && (
        <>
          <iframe src={objectUrl} title={title} />
          {/* Not every browser will display a PDF inline, and there is no reliable
              way to detect that from script, so the links above always show. */}
          <p className="hint">Nothing in the frame? Use “Open in a tab” instead.</p>
        </>
      )}
    </section>
  )
}
