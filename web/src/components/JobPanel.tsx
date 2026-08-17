import type { PollTrouble } from '../useJob'
import type { Job } from '../types'

interface Props {
  job: Job | null
  trouble: PollTrouble
  quiet: boolean
  onRetryJob: () => void
  onResumePolling: () => void
}

export function JobPanel({ job, trouble, quiet, onRetryJob, onResumePolling }: Props) {
  if (!job && !trouble) return null
  const running = job?.status === 'queued' || job?.status === 'running'

  return (
    <section className="card job">
      <header>
        <h2>
          <span className={`dot ${trouble ? 'failed' : (job?.status ?? 'queued')}`} aria-hidden="true" />
          {heading(job, trouble)}
        </h2>
        {job?.model && <span className="tag">{job.model}</span>}
      </header>

      {job && job.progress.length > 0 && (
        <ol className="progress">
          {job.progress.map((line, index) => (
            <li
              key={`${index}-${line}`}
              className={running && index === job.progress.length - 1 ? 'current' : ''}
            >
              {line}
            </li>
          ))}
        </ol>
      )}

      {quiet && !trouble && (
        <p className="hint">
          Still working. A long section can take a couple of minutes on its own.
        </p>
      )}

      {trouble?.kind === 'offline' && (
        <div className="failure">
          <p>Lost contact with the server: {trouble.message}</p>
          <button type="button" className="link" onClick={onResumePolling}>
            Try again
          </button>
        </div>
      )}

      {trouble?.kind === 'lost' && (
        <div className="failure">
          <p>
            This run disappeared, which usually means the server restarted. The work it had
            already paid for is cached, so starting it again is cheap.
          </p>
          <button type="button" className="link" onClick={onRetryJob}>
            Run it again
          </button>
        </div>
      )}

      {job?.error && (
        <div className="failure">
          <p>{job.error.message}</p>
          {job.error.retryable && (
            <button type="button" className="link" onClick={onRetryJob}>
              Try again
            </button>
          )}
        </div>
      )}

      {job?.record && (
        <dl className="facts">
          <div>
            <dt>Reading time</dt>
            <dd>{job.record.reading_time}</dd>
          </div>
          <div>
            <dt>Sections</dt>
            <dd>{job.record.sections}</dd>
          </div>
          <div>
            <dt>Model calls</dt>
            <dd>
              {job.record.calls}
              {job.record.cached_calls > 0 && ` (+${job.record.cached_calls} cached)`}
            </dd>
          </div>
          <div>
            <dt>Cost</dt>
            <dd>${job.record.cost_usd.toFixed(4)}</dd>
          </div>
          <div>
            <dt>Took</dt>
            <dd>{Math.round(job.record.seconds)}s</dd>
          </div>
        </dl>
      )}
    </section>
  )
}

function heading(job: Job | null, trouble: PollTrouble): string {
  if (trouble?.kind === 'lost') return 'That run is gone'
  if (trouble?.kind === 'offline') return 'Not sure how that run is doing'
  if (!job) return 'Waiting'
  if (job.status === 'queued') return 'Queued behind another run'
  if (job.status === 'running') return job.progress.at(-1) ?? 'Starting'
  if (job.status === 'failed') return 'That run failed'
  return job.record?.title ?? 'Finished'
}
