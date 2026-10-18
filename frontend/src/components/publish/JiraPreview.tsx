import { Icon } from '../ui/Icon'
import { Panel } from '../ui/Panel'
import './JiraPreview.css'

const MAPPING: [string, string][] = [
  ['Epic', 'Jira Epic'],
  ['Development story', 'Story under its epic, with acceptance criteria and story points'],
  ['Technical task', 'Sub-task whose description is its coding prompt'],
  ['UI screens (Validate design)', 'Images on the frontend sub-tasks of their user story'],
  ['Decision needed', 'Label “tech-decision-needed” on the sub-task'],
]

/** How development stories map to Jira issues when they're sent. */
export function JiraPreview() {
  return (
    <Panel
      title={
        <span className="jira-preview__title">
          <Icon name="branch" size={18} /> How it maps to Jira
        </span>
      }
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
      <p className="jira-preview__note">
        Nothing is sent until you confirm. Sending again updates the same issues, and nothing is ever deleted in Jira.
      </p>
    </Panel>
  )
}
