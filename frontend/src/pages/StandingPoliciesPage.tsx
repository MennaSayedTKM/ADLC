import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { PolicyDraft, StandingPolicy } from '../api/types'
import { Badge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import './StandingPoliciesPage.css'

export function StandingPoliciesPage() {
  const [policies, setPolicies] = useState<StandingPolicy[] | undefined>(undefined)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .listPolicies()
      .then(setPolicies)
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load policies'))
  }, [])

  function handleCreated(policy: StandingPolicy) {
    setPolicies((prev) => [...(prev ?? []), policy])
  }

  function handleUpdated(updated: StandingPolicy) {
    setPolicies((prev) => prev?.map((p) => (p.id === updated.id ? updated : p)))
  }

  return (
    <div className="policies-page">
      <div className="policies-page__header">
        <h1 className="policies-page__title">Standing policies</h1>
        <p className="policies-page__hint">
          Baseline expectations that apply to any project by default — the standard things almost
          every software project should get right regardless of client (accessibility, basic
          security, data retention, error handling, and the like), not something specific to one
          client or industry. When extraction runs, any active policy here is folded in as a
          fallback only where the client's own material doesn't already address the same topic —
          the client's material always wins.
        </p>
      </div>

      {error && <div className="policies-page__error">{error}</div>}

      {policies && (
        <ul className="policies-page__list">
          {policies.map((p) => (
            <PolicyCard key={p.id} policy={p} onUpdated={handleUpdated} />
          ))}
          {policies.length === 0 && <p className="policies-page__empty">No standing policies yet.</p>}
        </ul>
      )}

      <NewPolicyForm onCreated={handleCreated} />
    </div>
  )
}

type Mode = 'manual' | 'ai'

function NewPolicyForm({ onCreated }: { onCreated: (policy: StandingPolicy) => void }) {
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
      setError(err instanceof Error ? err.message : 'Could not add this policy')
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
          ✨ Add with AI
        </button>
      </div>

      {mode === 'manual' && (
        <form onSubmit={handleSubmit}>
          <input
            className="policy-form__title-input"
            placeholder="Policy title (e.g. Accessibility default)"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            disabled={busy}
          />
          <textarea
            className="policy-form__text-input"
            placeholder="Policy text — what applies by default when the client's own material is silent on this topic"
            value={policyText}
            onChange={(e) => setPolicyText(e.target.value)}
            disabled={busy}
            rows={3}
          />
          {error && <div className="policy-form__error">{error}</div>}
          <Button type="submit" variant="primary" size="sm" disabled={busy || !title.trim() || !policyText.trim()}>
            {busy ? 'Adding…' : 'Add policy'}
          </Button>
        </form>
      )}

      {mode === 'ai' && !draft && (
        <div>
          <textarea
            className="policy-form__text-input"
            autoFocus
            placeholder="Describe the policy area — the AI will draft a title and concrete default (e.g. 'session timeout for inactivity')"
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
          <label className="policy-form__field-label">Title</label>
          <input
            className="policy-form__title-input"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            disabled={busy}
          />
          <label className="policy-form__field-label">Policy text</label>
          <textarea
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
              {busy ? 'Adding…' : 'Add policy'}
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
      setError(err instanceof Error ? err.message : 'Could not update this policy')
    } finally {
      setBusy(false)
    }
  }

  return (
    <li className={`policy-card ${!policy.is_active ? 'policy-card--inactive' : ''}`}>
      <div className="policy-card__top">
        {editing ? (
          <input
            className="policy-card__title-input"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            disabled={busy}
          />
        ) : (
          <span className="policy-card__title">{policy.title}</span>
        )}
        <Badge tone={policy.is_active ? 'success' : 'neutral'}>{policy.is_active ? 'Active' : 'Inactive'}</Badge>
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
          <>
            <Button variant="secondary" size="sm" onClick={() => setEditing(true)} disabled={busy}>
              Edit
            </Button>
            <Button variant="ghost" size="sm" onClick={handleToggleActive} disabled={busy}>
              {policy.is_active ? 'Deactivate' : 'Reactivate'}
            </Button>
          </>
        )}
      </div>
    </li>
  )
}
