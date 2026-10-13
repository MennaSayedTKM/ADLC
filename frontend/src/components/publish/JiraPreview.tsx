import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { Icon } from '../ui/Icon'
import { Panel } from '../ui/Panel'
import './JiraPreview.css'

const MAPPING: [string, string][] = [
  ['Epic', 'Jira Epic'],
  ['User story', 'Jira Story'],
  ['Acceptance criteria', 'Description checklist'],
  ['Gap or open question', 'Task · label “needs-input”'],
  ['Priority (Must / Should)', 'Jira priority'],
]

/**
 * A static preview of how requirements would map to Jira. There is no Jira
 * connector and nothing here sends anything — it exists so the team can see
 * the direction and react to the mapping.
 */
export function JiraPreview() {
  return (
    <Panel
      title={
        <span className="jira-preview__title">
          <Icon name="branch" size={18} /> Preview: Jira stories
        </span>
      }
      description="See how your requirements will map when Jira export arrives."
      actions={<Badge tone="info">Beta preview</Badge>}
      className="jira-preview"
    >
      <ul className="jira-preview__list">
        {MAPPING.map(([from, to]) => (
          <li key={from} className="jira-preview__row">
            <span>{from}</span>
            <Icon name="arrow-right" size={15} />
            <span className="jira-preview__to">{to}</span>
          </li>
        ))}
      </ul>
      <div>
        <Button variant="secondary" size="sm" disabled title="Notifications are not available yet">
          Notify me when it&rsquo;s ready
        </Button>
      </div>
      <p className="jira-preview__note">Nothing is sent to Jira. Issues will only ever be created after you confirm.</p>
    </Panel>
  )
}
