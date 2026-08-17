import { useEffect, useState } from 'react'

import { api } from '../api'

interface Props {
  path: string
  title: string
}

export function PdfPreview({ path, title }: Props) {
  const [objectUrl, setObjectUrl] = useState<string | null>(null)
  const [problem, setProblem] = useState<string | null>(null)

  useEffect(() => {
    let current: string | null = null
    setObjectUrl(null)
    setProblem(null)

    api
      .fileUrl(path)
      .then((url) => {
        current = url
        setObjectUrl(url)
      })
      .catch((error: unknown) => {
        setProblem(error instanceof Error ? error.message : String(error))
      })

    // Object URLs pin the whole PDF in memory until revoked.
    return () => {
      if (current) URL.revokeObjectURL(current)
    }
  }, [path])

  return (
    <section className="card preview">
      <header>
        <h2>{title}</h2>
        {objectUrl && (
          <a href={objectUrl} download={`${title}.pdf`}>
            Download
          </a>
        )}
      </header>
      {problem && <p className="failure">Could not load the PDF: {problem}</p>}
      {objectUrl && <iframe src={objectUrl} title={title} />}
      {!objectUrl && !problem && <p className="hint">Loading the PDF…</p>}
    </section>
  )
}
