import { useState } from 'react'

interface Props {
  onSubmit: (password: string) => void
  problem: string | null
}

export function PasswordGate({ onSubmit, problem }: Props) {
  const [value, setValue] = useState('')

  return (
    <form
      className="card gate"
      onSubmit={(event) => {
        event.preventDefault()
        if (value) onSubmit(value)
      }}
    >
      <h2>This server is password protected</h2>
      <input
        type="password"
        value={value}
        onChange={(event) => setValue(event.target.value)}
        placeholder="Access password"
        autoFocus
      />
      {problem && <p className="failure">{problem}</p>}
      <button type="submit" disabled={!value}>
        Continue
      </button>
    </form>
  )
}
