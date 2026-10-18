import { useId, useRef, useState } from 'react'
import { api } from '../../api/client'
import type { TechProfile } from '../../api/types'
import { plural } from '../../lib/format'
import { Banner } from '../ui/Banner'
import { Button } from '../ui/Button'
import { Panel } from '../ui/Panel'
import { TECH_AREAS } from '../../lib/techAreas'

interface Props {
  projectId: string
  profile: TechProfile
  onSaved: () => void
}

/** The project's own stack, per area: typed in, or read from an uploaded document. */
export function TechStackPanel({ projectId, profile, onSaved }: Props) {
  const fieldId = useId()
  const fileInput = useRef<HTMLInputElement>(null)
  const [areas, setAreas] = useState<Record<string, string>>(profile.areas)
  const [saved, setSaved] = useState<Record<string, string>>(profile.areas)
  const [document, setDocument] = useState({ name: profile.document_name, chars: profile.document_chars })
  const [busy, setBusy] = useState<'save' | 'read' | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const dirty = TECH_AREAS.some((a) => (areas[a.key] ?? '') !== (saved[a.key] ?? ''))
  const unspecified = TECH_AREAS.filter((a) => !(areas[a.key] ?? '').trim())

  async function save() {
    setBusy('save')
    setError(null)
    setNotice(null)
    try {
      const result = await api.saveTechProfile(projectId, areas)
      setAreas(result.areas)
      setSaved(result.areas)
      setNotice('Tech stack saved. New coding prompts will use it.')
      onSaved()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save the tech stack')
    } finally {
      setBusy(null)
    }
  }

  async function readDocument(file: File) {
    setBusy('read')
    setError(null)
    setNotice(null)
    try {
      const result = await api.readTechDocument(projectId, file)
      setAreas(result.areas)
      setDocument({ name: result.document_name, chars: result.document_chars })
      const filled = TECH_AREAS.filter((a) => (result.read_from_document[a.key] ?? '').trim()).length
      setNotice(
        filled > 0
          ? `Read ${plural(filled, 'area')} from ${file.name} into the empty fields. Review them, then save.`
          : `${file.name} doesn’t name a technology for any area. Its text is still given to every coding prompt.`,
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not read that document')
    } finally {
      setBusy(null)
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  return (
    <Panel
      title="Tech stack"
      description="The company’s own technology, used in every coding prompt. Leave an area empty if it isn’t decided: the prompt then recommends an option, lists alternatives and flags the decision for the team."
      actions={
        <>
          <input
            ref={fileInput}
            type="file"
            accept=".pdf,.docx,.md,.txt"
            hidden
            onChange={(e) => e.target.files?.[0] && readDocument(e.target.files[0])}
          />
          <Button variant="secondary" size="sm" icon="upload" loading={busy === 'read'} disabled={busy !== null} onClick={() => fileInput.current?.click()}>
            Upload a stack document
          </Button>
        </>
      }
      className="tech-stack"
    >
      {document.name && (
        <p className="tech-stack__document">
          Using <strong>{document.name}</strong> ({document.chars.toLocaleString()} characters) as background for every
          coding prompt.
        </p>
      )}
      {notice && <Banner tone="success">{notice}</Banner>}
      {error && <Banner tone="danger">{error}</Banner>}

      <div className="tech-stack__grid">
        {TECH_AREAS.map((area) => (
          <div key={area.key} className="tech-stack__field">
            <label htmlFor={`${fieldId}-${area.key}`}>{area.label}</label>
            <textarea
              id={`${fieldId}-${area.key}`}
              rows={2}
              value={areas[area.key] ?? ''}
              placeholder={area.example}
              onChange={(e) => setAreas((prev) => ({ ...prev, [area.key]: e.target.value }))}
              disabled={busy !== null}
            />
          </div>
        ))}
      </div>

      <div className="tech-stack__footer">
        <p className="tech-stack__status">
          {unspecified.length === 0
            ? 'Every area is specified.'
            : `${plural(unspecified.length, 'area')} not specified — prompts will recommend options there.`}
        </p>
        <Button variant="primary" size="sm" loading={busy === 'save'} disabled={!dirty || busy !== null} onClick={save}>
          Save tech stack
        </Button>
      </div>
    </Panel>
  )
}
