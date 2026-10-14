import { useEffect, useId, useState } from 'react'
import { api } from '../api/client'
import type { PolicyDraft, StandingPolicy } from '../api/types'
import { Banner } from '../components/ui/Banner'
import { Button } from '../components/ui/Button'
import { Icon } from '../components/ui/Icon'
import { PageHeader } from '../components/ui/PageHeader'
import { Panel } from '../components/ui/Panel'
import { Toggle } from '../components/ui/Toggle'
import { plural } from '../lib/format'
import './StandingPoliciesPage.css'

/** Company standards: baseline rules applied to every project unless the client's own documents say otherwise. */
export function StandingPoliciesPage() {
  const [policies, setPolicies] = useState<StandingPolicy[] | undefined>(undefined)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .listPolicies()
      .then(setPolicies)
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load company standards'))
  }, [])

  function handleCreated(policy: StandingPolicy) {
    setPolicies((prev) => [...(prev ?? []), policy])
  }

  function handleUpdated(updated: StandingPolicy) {
    setPolicies((prev) => prev?.map((p) => (p.id === updated.id ? updated : p)))
  }

  const activeCount = policies?.filter((p) => p.is_active).length ?? 0

  return (
    <div className="page">
      <PageHeader
        title="Company standards"
        description="Baseline expectations that apply to every project — accessibility, basic security, data retention, error handling and the like. Switch each one on or off."
      />

      <Banner tone="info">
        <strong>Your client’s own documents always win.</strong> When requirements are generated, an active standard is
        only applied where the client’s material doesn’t already cover the same topic.
      </Banner>

      {error && <Banner tone="danger">{error}</Banner>}

      {policies && (
        <Panel
          title="Your standards"
          description={`${plural(activeCount, 'standard')} switched on of ${policies.length}.`}
        >
          {policies.length === 0 ? (
            <p className="policies-empty">No company standards yet. Add your first one below.</p>
          ) : (
            <ul className="policies-list">
              {policies.map((p) => (
                <PolicyCard key={p.id} policy={p} onUpdated={handleUpdated} />
              ))}
            </ul>
          )}
        </Panel>
      )}

      <Panel title="Add a standard" description="Write it yourself, or describe the area and let AI draft it for you to review.">
        <NewPolicyForm onCreated={handleCreated} />
      </Panel>
    </div>
  )
}

type Mode = 'manual' | 'ai'

function NewPolicyForm({ onCreated }: { onCreated: (policy: StandingPolicy) => void }) {
  const fieldId = useId()
  const [mode, setMode] = useState<Mode>('manual')
  const [title, setTitle] = useState('')
  const [policyText, setPolicyText] = useState('')
  const [subject, setSubject] = useState('')
  const [draft, setDraft] = useState<PolicyDraft | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function reset() {
    setTitle('')
    setPolicyText('')
    setSubject('')
    setDraft(null)
    setError(null)
  }

  function switchMode(next: Mode) {
    setMode(next)
    setTitle('')
    setPolicyText('')
    setDraft(null)
    setError(null)
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!title.trim() || !policyText.trim()) return
    setBusy(true)
    setError(null)
    try {
      const policy = await api.createPolicy(title.trim(), policyText.trim())
      onCreated(policy)
      reset()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not add this standard')
    } finally {
      setBusy(false)
    }
  }

  async function handleGenerate(regenerate = false) {
    if (!subject.trim()) return
    setBusy(true)
    setError(null)
    try {
      const result = await api.generatePolicyDraft(subject.trim(), regenerate && draft ? draft : undefined)
      setDraft(result)
      setTitle(result.title)
      setPolicyText(result.policy_text)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not generate a draft')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="policy-form">
      <div className="policy-form__mode-toggle" role="tablist">
        <button
          type="button"
          role="tab"
          className={`policy-form__mode-btn ${mode === 'manual' ? 'policy-form__mode-btn--active' : ''}`}
          onClick={() => switchMode('manual')}
          disabled={busy}
        >
          Add manually
        </button>
        <button
          type="button"
          role="tab"
          className={`policy-form__mode-btn ${mode === 'ai' ? 'policy-form__mode-btn--active' : ''}`}
          onClick={() => switchMode('ai')}
          disabled={busy}
        >
          Draft with AI
        </button>
      </div>

      {mode === 'manual' && (
        <form onSubmit={handleSubmit}>
          <input
            className="policy-form__title-input"
            aria-label="Standard title"
            placeholder="Title (e.g. Accessibility default)"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            disabled={busy}
          />
          <textarea
            className="policy-form__text-input"
            aria-label="What the standard says"
            placeholder="What applies by default when the client’s own material is silent on this topic"
            value={policyText}
            onChange={(e) => setPolicyText(e.target.value)}
            disabled={busy}
            rows={3}
          />
          {error && <div className="policy-form__error">{error}</div>}
          <Button type="submit" variant="primary" size="sm" disabled={busy || !title.trim() || !policyText.trim()}>
            {busy ? 'Adding…' : 'Add standard'}
          </Button>
        </form>
      )}

      {mode === 'ai' && !draft && (
        <div>
          <textarea
            className="policy-form__text-input"
            autoFocus
            aria-label="Area the standard should cover"
            placeholder="Describe the area — the AI will draft a title and a concrete default (e.g. 'session timeout for inactivity')"
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            disabled={busy}
            rows={2}
          />
          {error && <div className="policy-form__error">{error}</div>}
          <Button
            type="button"
            variant="primary"
            size="sm"
            onClick={() => handleGenerate(false)}
            disabled={busy || !subject.trim()}
          >
            {busy ? 'Generating…' : 'Generate'}
          </Button>
        </div>
      )}

      {mode === 'ai' && draft && (
        <div className="policy-form__draft-preview">
          <div className="policy-form__draft-badge">AI-drafted — review before adding</div>
          <label className="policy-form__field-label" htmlFor={`${fieldId}-title`}>Title</label>
          <input
            id={`${fieldId}-title`}
            className="policy-form__title-input"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            disabled={busy}
          />
          <label className="policy-form__field-label" htmlFor={`${fieldId}-text`}>Text</label>
          <textarea
            id={`${fieldId}-text`}
            className="policy-form__text-input"
            value={policyText}
            onChange={(e) => setPolicyText(e.target.value)}
            disabled={busy}
            rows={3}
          />
          {error && <div className="policy-form__error">{error}</div>}
          <div className="policy-form__draft-actions">
            <Button
              type="button"
              variant="primary"
              size="sm"
              onClick={handleSubmit}
              disabled={busy || !title.trim() || !policyText.trim()}
            >
              {busy ? 'Adding…' : 'Add standard'}
            </Button>
            <Button type="button" variant="secondary" size="sm" onClick={() => handleGenerate(true)} disabled={busy}>
              {busy ? 'Regenerating…' : 'Regenerate'}
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

function PolicyCard({
  policy,
  onUpdated,
}: {
  policy: StandingPolicy
  onUpdated: (policy: StandingPolicy) => void
}) {
  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState(policy.title)
  const [policyText, setPolicyText] = useState(policy.policy_text)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSave() {
    setBusy(true)
    setError(null)
    try {
      const updated = await api.updatePolicy(policy.id, { title: title.trim(), policy_text: policyText.trim() })
      onUpdated(updated)
      setEditing(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save changes')
    } finally {
      setBusy(false)
    }
  }

  async function handleToggleActive() {
    setBusy(true)
    setError(null)
    try {
      const updated = await api.updatePolicy(policy.id, { is_active: !policy.is_active })
      onUpdated(updated)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not update this standard')
    } finally {
      setBusy(false)
    }
  }

  return (
    <li className={`policy-card ${!policy.is_active ? 'policy-card--inactive' : ''}`}>
      <div className="policy-card__top">
        <span className="policy-card__icon" aria-hidden="true">
          <Icon name="shield" size={18} />
        </span>
        {editing ? (
          <input
            className="policy-card__title-input"
            value={title}
            aria-label="Standard title"
            onChange={(e) => setTitle(e.target.value)}
            disabled={busy}
          />
        ) : (
          <span className="policy-card__title">{policy.title}</span>
        )}
        <span className="policy-card__state">{policy.is_active ? 'On' : 'Off'}</span>
        <Toggle checked={policy.is_active} onChange={handleToggleActive} disabled={busy || editing} label={`${policy.title} is ${policy.is_active ? 'on' : 'off'}`} />
      </div>

      {editing ? (
        <textarea
          className="policy-card__text-input"
          value={policyText}
          onChange={(e) => setPolicyText(e.target.value)}
          disabled={busy}
          rows={3}
        />
      ) : (
        <p className="policy-card__text">{policy.policy_text}</p>
      )}

      {error && <div className="policy-form__error">{error}</div>}

      <div className="policy-card__actions">
        {editing ? (
          <>
            <Button variant="secondary" size="sm" onClick={handleSave} disabled={busy || !title.trim() || !policyText.trim()}>
              {busy ? 'Saving…' : 'Save'}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setEditing(false)
                setTitle(policy.title)
                setPolicyText(policy.policy_text)
              }}
              disabled={busy}
            >
              Cancel
            </Button>
          </>
        ) : (
          <Button variant="ghost" size="sm" icon="edit" onClick={() => setEditing(true)} disabled={busy}>
            Edit
          </Button>
        )}
      </div>
    </li>
  )
}
