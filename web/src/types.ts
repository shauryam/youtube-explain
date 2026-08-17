export type JobStatus = 'queued' | 'running' | 'done' | 'failed'

export interface JobFailure {
  kind: string
  message: string
  retryable: boolean
}

export interface RunRecord {
  pdf: string
  url: string
  video_id: string
  title: string
  model: string
  sections: number
  words: number
  reading_time: string
  cost_usd: number
  calls: number
  cached_calls: number
  seconds: number
  generated_at: string
  videos: number
  channel: string | null
  markdown: string | null
}

export interface Job {
  id: string
  url: string
  status: JobStatus
  model: string | null
  progress: string[]
  error: JobFailure | null
  pdf_url: string | null
  record: RunRecord | null
  created_at: number
}

/** A run record plus its path under the output directory, for /api/files. */
export interface HistoryEntry extends RunRecord {
  file: string
}

export interface ServerSettings {
  default_model: string
  requires_password: boolean
  max_jobs_per_hour: number
  has_api_key: boolean
}

export interface ModelInfo {
  id: string
  name: string
  context: number
  prompt_usd: number
  completion_usd: number
}

export interface JobSubmission {
  url: string
  model?: string
  fast: boolean
  markdown: boolean
  include_transcript: boolean
}
