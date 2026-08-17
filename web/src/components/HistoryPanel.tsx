import type { HistoryEntry } from '../types'

interface Props {
  entries: HistoryEntry[]
  problem: string | null
  selected: string | null
  onOpen: (entry: HistoryEntry) => void
  onRetry: () => void
}

export function HistoryPanel({ entries, problem, selected, onOpen, onRetry }: Props) {
  return (
    <section className="card history">
      <header>
        <h2>Earlier explainers</h2>
        <button type="button" className="link" onClick={onRetry}>
          Refresh
        </button>
      </header>

      {/* A failure here stays inside this panel: the rest of the page still works. */}
      {problem && (
        <p className="failure">
          Could not read the history: {problem}{' '}
          <button type="button" className="link" onClick={onRetry}>
            Try again
          </button>
        </p>
      )}
      {!problem && entries.length === 0 && (
        <p className="hint">Nothing here yet. Anything you generate, here or from the terminal, shows up in this list.</p>
      )}

      <ul>
        {entries.map((entry) => (
          <li key={entry.file}>
            <button
              type="button"
              className={selected === entry.file ? 'row selected' : 'row'}
              onClick={() => onOpen(entry)}
            >
              <span className="row-title">{entry.title}</span>
              <span className="row-meta">
                {[
                  entry.channel,
                  entry.reading_time,
                  entry.videos > 1 ? `${entry.videos} videos` : `${entry.sections} sections`,
                  entry.model,
                  entry.cost_usd > 0 ? `$${entry.cost_usd.toFixed(4)}` : 'from cache',
                  new Date(entry.generated_at).toLocaleDateString(),
                ]
                  .filter(Boolean)
                  .join(' · ')}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}
