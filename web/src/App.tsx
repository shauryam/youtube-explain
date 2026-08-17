import { useCallback, useEffect, useState } from 'react'

import { ApiError, api, describeError, token } from './api'
import { HistoryPanel } from './components/HistoryPanel'
import { JobPanel } from './components/JobPanel'
import { PasswordGate } from './components/PasswordGate'
import { PdfPreview } from './components/PdfPreview'
import { SubmitForm } from './components/SubmitForm'
import type { HistoryEntry, JobSubmission, ModelInfo, ServerSettings } from './types'
import { formatWait, useCountdown } from './useCountdown'
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
  const [lastSubmission, setLastSubmission] = useState<JobSubmission | null>(null)
  const [submitProblem, setSubmitProblem] = useState<string | null>(null)
  const [preview, setPreview] = useState<Preview | null>(null)
  const [cooldown, startCooldown] = useCountdown()

  // A rejected password is only worth reporting once, at the gate.
  const forgetPassword = useCallback((message: string) => {
    token.clear()
    setAuthorised(false)
    setGateProblem(message)
  }, [])

  const onUnauthorised = useCallback(
    () => forgetPassword('The password stopped working. Enter it again.'),
    [forgetPassword],
  )

  const { job, trouble, quiet, retry: resumePolling } = useJob(jobId, onUnauthorised)
  const busy = job?.status === 'queued' || job?.status === 'running'

  useEffect(() => {
    api
      .settings()
      .then((loaded) => {
        setSettings(loaded)
        setAuthorised(!loaded.requires_password || Boolean(token.read()))
      })
      .catch((error: unknown) => setSubmitProblem(describeError(error)))
  }, [])

  const loadHistory = useCallback(() => {
    api
      .history()
      .then((entries) => {
        setHistory(entries)
        setHistoryProblem(null)
      })
      .catch((error: unknown) => {
        if (error instanceof ApiError && error.status === 401) {
          forgetPassword('The password stopped working. Enter it again.')
          return
        }
        setHistoryProblem(describeError(error))
      })
  }, [forgetPassword])

  useEffect(() => {
    if (!authorised) return
    loadHistory()
    // A missing catalogue only costs the dropdown, so it fails quietly.
    api.models().then(setModels).catch(() => setModels([]))
  }, [authorised, loadHistory])

  useEffect(() => {
    if (job?.status === 'done' && job.pdf_url) {
      setPreview({ path: job.pdf_url, title: job.record?.title ?? 'Explainer', file: null })
      loadHistory()
    }
  }, [job?.status, job?.pdf_url, job?.record?.title, loadHistory])

  const submit = useCallback(
    (submission: JobSubmission) => {
      setSubmitProblem(null)
      setPreview(null)
      setLastSubmission(submission)
      api
        .submit(submission)
        .then((created) => setJobId(created.id))
        .catch((error: unknown) => {
          if (error instanceof ApiError && error.status === 401) {
            forgetPassword('The password stopped working. Enter it again.')
            return
          }
          if (error instanceof ApiError && error.status === 429) {
            startCooldown(error.retryAfter ?? 60)
          }
          setSubmitProblem(describeError(error))
        })
    },
    [forgetPassword, startCooldown],
  )

  const openGate = (password: string) => {
    token.write(password)
    setGateProblem(null)
    // Any authorised endpoint will do; history is the cheapest.
    api
      .history()
      .then((entries) => {
        setHistory(entries)
        setAuthorised(true)
      })
      .catch((error: unknown) => {
        token.clear()
        setGateProblem(
          error instanceof ApiError && error.status === 401
            ? 'That password was not accepted.'
            : describeError(error),
        )
      })
  }

  if (settings?.requires_password && !authorised) {
    return (
      <Shell>
        <PasswordGate problem={gateProblem} onSubmit={openGate} />
      </Shell>
    )
  }

  return (
    <Shell>
      {settings && (
        <SubmitForm
          settings={settings}
          models={models}
          busy={busy}
          cooldown={cooldown}
          onSubmit={submit}
        />
      )}
      {settings && !settings.has_api_key && (
        <p className="failure card">
          The server has no OPENROUTER_API_KEY set, so runs will fail until it does.
        </p>
      )}
      {submitProblem && (
        <p className="failure card">
          {submitProblem}
          {cooldown > 0 && (
            <span className="countdown"> Try again in {formatWait(cooldown)}.</span>
          )}
        </p>
      )}

      <JobPanel
        job={job}
        trouble={trouble}
        quiet={quiet}
        onRetryJob={() => lastSubmission && submit(lastSubmission)}
        onResumePolling={resumePolling}
      />
      {preview && <PdfPreview path={preview.path} title={preview.title} />}

      <HistoryPanel
        entries={history}
        problem={historyProblem}
        selected={preview?.file ?? null}
        onRetry={loadHistory}
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
