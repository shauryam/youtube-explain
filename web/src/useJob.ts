import { useEffect, useState } from 'react'

import { api } from './api'
import type { Job } from './types'

const POLL_MS = 1000

/**
 * Follow a job until it finishes.
 *
 * Each poll schedules the next one rather than running on an interval, so a slow
 * response cannot stack requests, and polling stops the moment the job is done.
 */
export function useJob(jobId: string | null) {
  const [job, setJob] = useState<Job | null>(null)
  const [problem, setProblem] = useState<string | null>(null)

  useEffect(() => {
    setJob(null)
    setProblem(null)
    if (!jobId) return

    let cancelled = false
    let timer = 0

    const poll = async () => {
      try {
        const next = await api.job(jobId)
        if (cancelled) return
        setJob(next)
        setProblem(null)
        if (next.status === 'queued' || next.status === 'running') {
          timer = window.setTimeout(poll, POLL_MS)
        }
      } catch (error) {
        if (cancelled) return
        setProblem(error instanceof Error ? error.message : String(error))
      }
    }

    void poll()
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [jobId])

  return { job, problem }
}
