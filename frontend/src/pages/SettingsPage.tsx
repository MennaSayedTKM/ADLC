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

export function SettingsPage() {
  const { preference, setPreference } = useTheme()

  return (
    <div className="page">
      <PageHeader title="Settings" description="Preferences for this browser." />

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
