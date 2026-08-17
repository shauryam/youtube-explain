import { useState } from 'react'

import type { JobSubmission, ModelInfo, ServerSettings } from '../types'
import { formatWait } from '../useCountdown'

interface Props {
  settings: ServerSettings
  models: ModelInfo[]
  busy: boolean
  cooldown: number
  onSubmit: (submission: JobSubmission) => void
}

export function SubmitForm({ settings, models, busy, cooldown, onSubmit }: Props) {
  const [url, setUrl] = useState('')
  const [model, setModel] = useState('')
  const [fast, setFast] = useState(false)
  const [markdown, setMarkdown] = useState(false)
  const [includeTranscript, setIncludeTranscript] = useState(false)

  // One worker runs the jobs, so a second submission would only sit in a queue.
  const blocked = busy || cooldown > 0

  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    if (!url.trim() || blocked) return
    onSubmit({
      url: url.trim(),
      model: model || undefined,
      fast,
      markdown,
      include_transcript: includeTranscript,
    })
  }

  return (
    <form className="card submit" onSubmit={submit}>
      <label className="field">
        <span>YouTube video</span>
        <input
          type="text"
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          placeholder="https://www.youtube.com/watch?v=..."
          autoFocus
          spellCheck={false}
        />
      </label>

      <label className="field">
        <span>Model</span>
        <select value={model} onChange={(event) => setModel(event.target.value)}>
          <option value="">Server default ({settings.default_model})</option>
          {models.map((entry) => (
            <option key={entry.id} value={entry.id}>
              {entry.name} — ${entry.prompt_usd.toFixed(2)}/${entry.completion_usd.toFixed(2)} per M
            </option>
          ))}
        </select>
      </label>

      <div className="toggles">
        <label>
          <input type="checkbox" checked={fast} onChange={(e) => setFast(e.target.checked)} />
          Fast (one call, cheaper, shorter)
        </label>
        <label>
          <input type="checkbox" checked={markdown} onChange={(e) => setMarkdown(e.target.checked)} />
          Also write Markdown
        </label>
        <label>
          <input
            type="checkbox"
            checked={includeTranscript}
            onChange={(e) => setIncludeTranscript(e.target.checked)}
          />
          Append the transcript
        </label>
      </div>

      <button type="submit" disabled={blocked || !url.trim()}>
        {cooldown > 0
          ? `Hourly limit reached — ${formatWait(cooldown)}`
          : busy
            ? 'Working…'
            : 'Explain this video'}
      </button>
      <p className="hint">
        One video at a time. Playlists are not supported yet, and a typical run takes a minute or two.
        This server allows {settings.max_jobs_per_hour}{' '}
        {settings.max_jobs_per_hour === 1 ? 'run' : 'runs'} an hour.
      </p>
    </form>
  )
}
