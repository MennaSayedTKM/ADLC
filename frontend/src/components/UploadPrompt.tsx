import { useRef, useState } from 'react'
import { Button } from './ui/Button'
import './UploadPrompt.css'

interface UploadPromptProps {
  onUpload: (file: File) => Promise<void>
  icon?: string
  title?: string
  body?: string
  progressLabel?: string
  disabled?: boolean
  disabledMessage?: string
  accept?: string
}

const DEFAULT_ACCEPTED = '.pdf,.png,.jpg,.jpeg,.webp,.bmp,.tiff'

export function UploadPrompt({
  onUpload,
  icon = '📄',
  title = 'No requirements uploaded yet',
  body = "Upload a requirements document (PDF or image). It'll be rendered page by page and sent to GPT-4o to extract epics, user stories, acceptance criteria, and any gaps it notices.",
  progressLabel = 'Rendering pages, embedding, and running GPT-4o extraction…',
  disabled = false,
  disabledMessage,
  accept = DEFAULT_ACCEPTED,
}: UploadPromptProps) {
  const [dragOver, setDragOver] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  async function handleFile(file: File) {
    if (disabled) return
    setBusy(true)
    setError(null)
    try {
      await onUpload(file)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      className={`upload-prompt ${dragOver ? 'upload-prompt--drag' : ''}`}
      onDragOver={(e) => {
        if (disabled) return
        e.preventDefault()
        setDragOver(true)
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDragOver(false)
        if (disabled) return
        const file = e.dataTransfer.files?.[0]
        if (file) handleFile(file)
      }}
    >
      <div className="upload-prompt__icon">{icon}</div>
      <h2 className="upload-prompt__title">{title}</h2>
      <p className="upload-prompt__body">{body}</p>

      {disabled ? (
        <div className="upload-prompt__disabled">{disabledMessage}</div>
      ) : busy ? (
        <div className="upload-prompt__progress">
          <span className="upload-prompt__spinner" />
          {progressLabel}
        </div>
      ) : (
        <Button variant="primary" onClick={() => inputRef.current?.click()}>
          Choose a file
        </Button>
      )}

      {error && <div className="upload-prompt__error">{error}</div>}

      <input
        ref={inputRef}
        type="file"
        accept={accept}
        hidden
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) handleFile(file)
          e.target.value = ''
        }}
      />

      {!disabled && <p className="upload-prompt__hint">or drag a file anywhere onto this box</p>}
    </div>
  )
}
