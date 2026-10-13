import { api } from '../../api/client'
import { plural } from '../../lib/format'
import { ButtonLink } from '../ui/Button'
import { Icon } from '../ui/Icon'
import { Panel } from '../ui/Panel'
import './DiagramsTab.css'

interface DiagramsTabProps {
  projectId: string
  docId: string
  storyCount: number
}

/**
 * Use-case diagrams are drawn by the PDF/Confluence exporter, not stored as
 * images the app can show, so this tab explains where they live rather than
 * pretending to preview them.
 */
export function DiagramsTab({ projectId, docId, storyCount }: DiagramsTabProps) {
  return (
    <Panel tone="sunken" className="diagrams">
      <div className="diagrams__icon" aria-hidden="true">
        <Icon name="diagram" size={28} />
      </div>
      <h2 className="diagrams__title">A diagram for every story, in your export</h2>
      <p className="diagrams__body">
        We draw a UML use-case diagram for each of your {plural(storyCount, 'story', 'stories')} — who uses it and what
        they can do. They’re generated when you export, so they always match the stories as they are right now, and
        they appear in the business requirements PDF and on the Confluence page.
      </p>
      <p className="diagrams__hint">The first export can take a little longer while diagrams are drawn; later ones reuse them.</p>
      <div className="diagrams__actions">
        <ButtonLink variant="primary" icon="download" href={api.exportPdfUrl(projectId, docId, 'business')} download>
          Export business PDF
        </ButtonLink>
      </div>
    </Panel>
  )
}
