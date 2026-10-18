import { useEffect, useId, useState } from 'react'
import { api } from '../api/client'
import { Banner } from '../components/ui/Banner'
import { Button } from '../components/ui/Button'
import { Icon, type IconName } from '../components/ui/Icon'
import { PageHeader } from '../components/ui/PageHeader'
import { Panel } from '../components/ui/Panel'
import { useTheme, type ThemePreference } from '../lib/theme'
import './SettingsPage.css'

const THEMES: { value: ThemePreference; label: string; hint: string; icon: IconName }[] = [
  { value: 'system', label: 'Match my system', hint: 'Follows your device setting', icon: 'monitor' },
  { value: 'light', label: 'Light', hint: 'Bright surfaces, indigo accent', icon: 'sun' },
  { value: 'dark', label: 'Dark', hint: 'Easy on the eyes in low light', icon: 'moon' },
]

const SHORTCUTS: [string, string][] = [
  ['⌘K  or  Ctrl+K', 'Search stories, gaps, pages and projects'],
  ['Esc', 'Close a dialog, drawer or search'],
  ['← →', 'Move between tabs'],
]

/** The company-wide default Jira project: projects without one of their own connect to it automatically. */
function JiraDefaultPanel() {
  const inputId = useId()
  const [saved, setSaved] = useState<string | null | undefined>(undefined) // undefined = loading
  const [key, setKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .getJiraDefault()
      .then((r) => {
        setSaved(r.default_project_key)
        setKey(r.default_project_key ?? '')
      })
      .catch((err) => setError(err instanceof Error ? err.message : 'Could not load the Jira default'))
  }, [])

  async function save() {
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const r = await api.saveJiraDefault(key)
      setSaved(r.default_project_key)
      setKey(r.default_project_key ?? '')
      setNotice(r.default_project_key ? `New projects now connect to ${r.default_project_key} automatically.` : 'The company default was cleared.')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save the Jira default')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Panel
      title="Company default Jira project"
      description="For the whole company, not just this browser. A project with no Jira project of its own connects to this key automatically; it can still choose another on its Dev stories page."
    >
      <form
        className="settings-jira"
        onSubmit={(e) => {
          e.preventDefault()
          save()
        }}
      >
        <label htmlFor={inputId}>Jira project key</label>
        <div className="settings-jira__row">
          <input
            id={inputId}
            value={key}
            onChange={(e) => setKey(e.target.value.toUpperCase())}
            placeholder="e.g. TK (leave empty for none)"
            maxLength={20}
            autoComplete="off"
            spellCheck={false}
            disabled={busy || saved === undefined}
          />
          <Button type="submit" variant="primary" size="sm" loading={busy} disabled={saved === undefined || key.trim() === (saved ?? '')}>
            Save
          </Button>
        </div>
        <p className="settings-jira__hint">
          The prefix of the project’s issue numbers (TK in TK-146). Saving doesn’t contact Jira; each project checks the key
          when it first connects.
        </p>
      </form>
      {notice && <Banner tone="success">{notice}</Banner>}
      {error && <Banner tone="danger">{error}</Banner>}
    </Panel>
  )
}

export function SettingsPage() {
  const { preference, setPreference } = useTheme()

  return (
    <div className="page">
      <PageHeader title="Settings" description="Preferences for this browser, and a few settings for the whole company." />

      <Panel title="Appearance" description="The indigo brand colour stays the same in both themes.">
        <div className="theme-options" role="radiogroup" aria-label="Theme">
          {THEMES.map((theme) => (
            <label key={theme.value} className={`theme-option ${preference === theme.value ? 'theme-option--active' : ''}`}>
              <input
                type="radio"
                name="theme"
                className="sr-only"
                checked={preference === theme.value}
                onChange={() => setPreference(theme.value)}
              />
              <span className="theme-option__icon" aria-hidden="true">
                <Icon name={theme.icon} size={20} />
              </span>
              <span className="theme-option__label">{theme.label}</span>
              <span className="theme-option__hint">{theme.hint}</span>
            </label>
          ))}
        </div>
      </Panel>

      <JiraDefaultPanel />

      <Panel title="Keyboard shortcuts">
        <dl className="shortcuts">
          {SHORTCUTS.map(([keys, action]) => (
            <div key={keys} className="shortcuts__row">
              <dt>
                <kbd className="shortcuts__kbd">{keys}</kbd>
              </dt>
              <dd>{action}</dd>
            </div>
          ))}
        </dl>
      </Panel>
    </div>
  )
}
