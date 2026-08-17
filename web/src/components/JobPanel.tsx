import type { Job } from '../types'

interface Props {
  job: Job
}

export function JobPanel({ job }: Props) {
  const running = job.status === 'queued' || job.status === 'running'

  return (
    <section className="card job">
      <header>
        <h2>
          <span className={`dot ${job.status}`} aria-hidden="true" />
          {label(job)}
        </h2>
        {job.model && <span className="tag">{job.model}</span>}
      </header>

      <ol className="progress">
        {job.progress.map((line, index) => (
          <li key={`${index}-${line}`} className={running && index === job.progress.length - 1 ? 'current' : ''}>
            {line}
          </li>
        ))}
      </ol>

      {job.error && (
        <div className="failure">
          <strong>{job.error.message}</strong>
        </div>
      )}

      {job.record && (
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

function label(job: Job): string {
  if (job.status === 'queued') return 'Queued behind another run'
  if (job.status === 'running') return job.progress.at(-1) ?? 'Starting'
  if (job.status === 'failed') return 'That run failed'
  return job.record?.title ?? 'Finished'
}
