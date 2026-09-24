import { useState } from 'react'
import { api } from '../api/client'
import type { TextIngestResponse } from '../api/types'
import { Button } from './ui/Button'
import './RunExtractionPanel.css'

interface RunExtractionPanelProps {
  projectId: string
  onExtracted: (result: TextIngestResponse) => Promise<void>
}

export function RunExtractionPanel({ projectId, onExtracted }: RunExtractionPanelProps) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleRun() {
    setBusy(true)
    setError(null)
    try {
      const result = await api.runStagedExtraction(projectId)
      await onExtracted(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Extraction failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="run-extraction-panel">
      <div>
        <p className="run-extraction-panel__title">Ready to run extraction</p>
        <p className="run-extraction-panel__hint">
          Combines every staged resource, answered clarifying question, and active standing
          policy into one extraction — the client's own material always takes priority over a
          standing policy on the same topic. Requires at least one primary requirements resource.
        </p>
      </div>
      {busy ? (
        <div className="run-extraction-panel__progress">
          <span className="run-extraction-panel__spinner" />
          Extracting text and running LLM extraction…
        </div>
      ) : (
        <Button variant="primary" onClick={handleRun}>
          Run extraction
        </Button>
      )}
      {error && <div className="run-extraction-panel__error">{error}</div>}
    </div>
  )
}
