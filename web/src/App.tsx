import { useCallback, useEffect, useState } from 'react'

import { ApiError, api, token } from './api'
import { HistoryPanel } from './components/HistoryPanel'
import { JobPanel } from './components/JobPanel'
import { PasswordGate } from './components/PasswordGate'
import { PdfPreview } from './components/PdfPreview'
import { SubmitForm } from './components/SubmitForm'
import type { HistoryEntry, JobSubmission, ModelInfo, ServerSettings } from './types'
import { useJob } from './useJob'

interface Preview {
  path: string
  title: string
  file: string | null
}

export default function App() {
  const [settings, setSettings] = useState<ServerSettings | null>(null)
  const [authorised, setAuthorised] = useState(false)
  const [gateProblem, setGateProblem] = useState<string | null>(null)
  const [models, setModels] = useState<ModelInfo[]>([])
  const [history, setHistory] = useState<HistoryEntry[]>([])
  const [historyProblem, setHistoryProblem] = useState<string | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const [submitProblem, setSubmitProblem] = useState<string | null>(null)
  const [preview, setPreview] = useState<Preview | null>(null)

  const { job, problem: pollProblem } = useJob(jobId)
  const busy = job?.status === 'queued' || job?.status === 'running'

  useEffect(() => {
    api
      .settings()
      .then((loaded) => {
        setSettings(loaded)
        setAuthorised(!loaded.requires_password || Boolean(token.read()))
      })
      .catch((error: unknown) => setSubmitProblem(describe(error)))
  }, [])

  const loadHistory = useCallback(() => {
    api
      .history()
      .then((entries) => {
        setHistory(entries)
        setHistoryProblem(null)
      })
      .catch((error: unknown) => setHistoryProblem(describe(error)))
  }, [])

  useEffect(() => {
    if (!authorised) return
    loadHistory()
    api.models().then(setModels).catch(() => setModels([]))
  }, [authorised, loadHistory])

  // A finished run becomes the preview, and joins the history list.
  useEffect(() => {
    if (job?.status === 'done' && job.pdf_url) {
      setPreview({ path: job.pdf_url, title: job.record?.title ?? 'Explainer', file: null })
      loadHistory()
    }
  }, [job?.status, job?.pdf_url, job?.record?.title, loadHistory])

  const submit = (submission: JobSubmission) => {
    setSubmitProblem(null)
    setPreview(null)
    api
      .submit(submission)
      .then((created) => setJobId(created.id))
      .catch((error: unknown) => setSubmitProblem(describe(error)))
  }

  if (settings?.requires_password && !authorised) {
    return (
      <Shell>
        <PasswordGate
          problem={gateProblem}
          onSubmit={(password) => {
            token.write(password)
            setGateProblem(null)
            api
              .history()
              .then(() => setAuthorised(true))
              .catch((error: unknown) => {
                token.clear()
                setGateProblem(
                  error instanceof ApiError && error.status === 401
                    ? 'That password was not accepted.'
                    : describe(error),
                )
              })
          }}
        />
      </Shell>
    )
  }

  return (
    <Shell>
      {settings && (
        <SubmitForm settings={settings} models={models} busy={busy} onSubmit={submit} />
      )}
      {settings && !settings.has_api_key && (
        <p className="failure card">
          The server has no OPENROUTER_API_KEY set, so runs will fail until it does.
        </p>
      )}
      {submitProblem && <p className="failure card">{submitProblem}</p>}
      {pollProblem && <p className="failure card">{pollProblem}</p>}

      {job && <JobPanel job={job} />}
      {preview && <PdfPreview path={preview.path} title={preview.title} />}

      <HistoryPanel
        entries={history}
        problem={historyProblem}
        selected={preview?.file ?? null}
        onOpen={(entry) =>
          setPreview({
            path: `/api/files/${entry.file.split('/').map(encodeURIComponent).join('/')}`,
            title: entry.title,
            file: entry.file,
          })
        }
      />
    </Shell>
  )
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="page">
      <header className="masthead">
        <h1>ytexplain</h1>
        <p>Read the explainer instead of watching the video.</p>
      </header>
      {children}
    </div>
  )
}

function describe(error: unknown): string {
  if (error instanceof ApiError) return error.message
  // fetch rejects with a TypeError when the request never reached the server.
  if (error instanceof TypeError) return 'Could not reach the server.'
  return error instanceof Error ? error.message : String(error)
}
