import { useEffect, useState } from 'react'

/** Seconds remaining, ticking down to zero. Used for the hourly-limit wait. */
export function useCountdown(): [number, (seconds: number) => void] {
  const [left, setLeft] = useState(0)

  useEffect(() => {
    if (left <= 0) return
    const timer = window.setTimeout(() => setLeft((value) => value - 1), 1000)
    return () => window.clearTimeout(timer)
  }, [left])

  return [left, (seconds: number) => setLeft(Math.max(0, Math.ceil(seconds)))]
}

/** "59m 36s" rather than "3576s", which nobody can read as a wait. */
export function formatWait(seconds: number): string {
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  return `${minutes}m ${String(seconds % 60).padStart(2, '0')}s`
}
