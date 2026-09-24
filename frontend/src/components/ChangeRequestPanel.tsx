import { useRef, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { ChangeRequestIngestResponse, CrRequestType } from '../api/types'
import { Button } from './ui/Button'
import { CrDocumentIcon } from './ui/CrDocumentIcon'
import './ChangeRequestPanel.css'

const REQUEST_TYPES: CrRequestType[] = [
  'New Feature',
  'Enhancement',
  'Configuration',
  'Report',
  'Integration',
  'Business Support',
]

const CLASSIFICATIONS = ['Small', 'Medium', 'Large']

interface ChangeRequestPanelProps {
  projectId: string
  onFiled: (result: ChangeRequestIngestResponse) => Promise<void>
}

export function ChangeRequestPanel({ projectId, onFiled }: ChangeRequestPanelProps) {
  const [open, setOpen] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [requestType, setRequestType] = useState<CrRequestType | ''>('')
  const [classification, setClassification] = useState('')
  const [estimatedEffort, setEstimatedEffort] = useState('')
  const [estimatedCost, setEstimatedCost] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  function reset() {
    setFile(null)
    setRequestType('')
    setClassification('')
    setEstimatedEffort('')
    setEstimatedCost('')
    setError(null)
    setOpen(false)
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!file || !requestType) return
    setBusy(true)
    setError(null)
    try {
      const result = await api.uploadChangeRequest(projectId, file, {
        request_type: requestType,
        classification: classification.trim() || undefined,
        estimated_effort: estimatedEffort.trim() || undefined,
        estimated_cost: estimatedCost.trim() || undefined,
      })
      await onFiled(result)
      reset()
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 409
          ? 'This project has no approved requirements version yet — file this once an initial version is approved.'
          : err instanceof Error
            ? err.message
            : 'Could not file the change request',
      )
    } finally {
      setBusy(false)
    }
  }

  if (!open) {
    return (
      <button type="button" className="cr-panel-trigger" onClick={() => setOpen(true)}>
        <CrDocumentIcon /> File a Change Request
      </button>
    )
  }

  return (
    <form className="cr-panel" onSubmit={handleSubmit}>
      <div className="cr-panel__heading">File a Change Request</div>

      <label className="cr-panel__field-label">CR document</label>
      <Button type="button" variant="secondary" size="sm" onClick={() => inputRef.current?.click()} disabled={busy}>
        {file ? file.name : 'Choose file'}
      </Button>
      <input
        ref={inputRef}
        type="file"
        accept=".pdf,.docx,.doc"
        hidden
        onChange={(e) => setFile(e.target.files?.[0] ?? null)}
      />

      <label className="cr-panel__field-label">Request Type *</label>
      <select
        className="cr-panel__select"
        value={requestType}
        onChange={(e) => setRequestType(e.target.value as CrRequestType)}
        disabled={busy}
        required
      >
        <option value="" disabled>
          Select a request type…
        </option>
        {REQUEST_TYPES.map((t) => (
          <option key={t} value={t}>
            {t}
          </option>
        ))}
      </select>

      <div className="cr-panel__optional-grid">
        <div>
          <label className="cr-panel__field-label">Classification</label>
          <select
            className="cr-panel__select"
            value={classification}
            onChange={(e) => setClassification(e.target.value)}
            disabled={busy}
          >
            <option value="">Select…</option>
            {CLASSIFICATIONS.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="cr-panel__field-label">Estimated effort</label>
          <input
            className="cr-panel__input"
            placeholder="e.g. 35 man-days"
            value={estimatedEffort}
            onChange={(e) => setEstimatedEffort(e.target.value)}
            disabled={busy}
          />
        </div>
        <div>
          <label className="cr-panel__field-label">Estimated cost</label>
          <input
            className="cr-panel__input"
            placeholder="e.g. SAR amount"
            value={estimatedCost}
            onChange={(e) => setEstimatedCost(e.target.value)}
            disabled={busy}
          />
        </div>
      </div>

      {error && <div className="cr-panel__error">{error}</div>}

      <div className="cr-panel__actions">
        <Button type="submit" variant="primary" size="sm" disabled={busy || !file || !requestType}>
          {busy ? 'Filing…' : 'File change request'}
        </Button>
        <Button type="button" variant="ghost" size="sm" onClick={reset} disabled={busy}>
          Cancel
        </Button>
      </div>
    </form>
  )
}
