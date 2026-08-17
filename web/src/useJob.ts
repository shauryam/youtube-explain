import { useCallback, useEffect, useState } from 'react'

import { ApiError, api, describeError } from './api'
import type { Job } from './types'

const POLL_MS = 1000
const MAX_FAILURES = 3
const MAX_BACKOFF_MS = 4000
// One section can legitimately take minutes on a slow model, so silence is not
// the same as trouble. This threshold only changes the wording on screen.
const QUIET_MS = 120_000

export type PollTrouble =
  | { kind: 'offline'; message: string }
  | { kind: 'lost' }
  | { kind: 'unauthorised' }
  | null

export interface JobWatch {
  job: Job | null
  trouble: PollTrouble
  quiet: boolean
  retry: () => void
}

/**
 * Follow a job until it finishes, and say why if following stops working.
 *
 * Each poll schedules the next, so slow responses cannot stack up. A failed poll
 * is retried three times with widening gaps before giving up: a laptop waking or
 * a server reloading should not be reported as a dead run, but a server that has
 * actually stopped should not look like a job that is thinking either.
 */
export function useJob(jobId: string | null, onUnauthorised: () => void): JobWatch {
  const [job, setJob] = useState<Job | null>(null)
  const [trouble, setTrouble] = useState<PollTrouble>(null)
  const [quiet, setQuiet] = useState(false)
  const [attempt, setAttempt] = useState(0)

  const retry = useCallback(() => setAttempt((value) => value + 1), [])

  useEffect(() => {
    setTrouble(null)
    setQuiet(false)
    if (!jobId) {
      setJob(null)
      return
    }

    let cancelled = false
    let timer = 0
    let failures = 0
    let seen = -1
    let changedAt = Date.now()

    const poll = async () => {
      try {
        const next = await api.job(jobId)
        if (cancelled) return
        failures = 0
        setTrouble(null)
        setJob(next)

        if (next.progress.length !== seen) {
          seen = next.progress.length
          changedAt = Date.now()
        }
        const running = next.status === 'queued' || next.status === 'running'
        setQuiet(running && Date.now() - changedAt > QUIET_MS)
        if (running) timer = window.setTimeout(poll, POLL_MS)
      } catch (error) {
        if (cancelled) return
        if (error instanceof ApiError && error.status === 404) {
          // The job id is unknown, which is also what a restart looks like.
          setTrouble({ kind: 'lost' })
          return
        }
        if (error instanceof ApiError && error.status === 401) {
          setTrouble({ kind: 'unauthorised' })
          onUnauthorised()
          return
        }
        failures += 1
        if (failures > MAX_FAILURES) {
          setTrouble({ kind: 'offline', message: describeError(error) })
          return
        }
        // Capped: the point is to ride out a blip, and a stopped server should be
        // reported in a few seconds rather than after half a minute of silence.
        timer = window.setTimeout(poll, Math.min(POLL_MS * 2 ** failures, MAX_BACKOFF_MS))
      }
    }

    void poll()
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
    // `attempt` restarts polling after it gave up; onUnauthorised is stable.
  }, [jobId, attempt, onUnauthorised])

  return { job, trouble, quiet, retry }
}
