import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
}

interface State {
  message: string | null
}

/**
 * Keeps a render bug from leaving a white page.
 *
 * Worth having here specifically because the interesting state — a run in
 * progress — is on the server: reloading recovers the page without losing work.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { message: null }

  static getDerivedStateFromError(error: unknown): State {
    return { message: error instanceof Error ? error.message : String(error) }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Page failed to render', error, info.componentStack)
  }

  render() {
    if (this.state.message === null) return this.props.children
    return (
      <div className="page">
        <div className="card">
          <h2>The page hit a bug</h2>
          <p className="failure">{this.state.message}</p>
          <p className="hint">
            Any run in progress is still going on the server, so reloading will not lose it.
          </p>
          <button type="button" onClick={() => window.location.reload()}>
            Reload
          </button>
        </div>
      </div>
    )
  }
}
