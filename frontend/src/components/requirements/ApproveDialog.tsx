import { useState } from 'react'
import { plural } from '../../lib/format'
import { Banner } from '../ui/Banner'
import { Button } from '../ui/Button'
import { Icon } from '../ui/Icon'
import { Modal } from '../ui/Modal'
import './ApproveDialog.css'

interface ApproveDialogProps {
  open: boolean
  version: number
  openGaps: number
  onClose: () => void
  onApprove: () => Promise<void>
  onReviewGaps: () => void
}

/**
 * Approval is the one step that can't be quietly undone, so it gets its own
 * explanation: what gets locked, and what an open gap means for the decision.
 */
export function ApproveDialog({ open, version, openGaps, onClose, onApprove, onReviewGaps }: ApproveDialogProps) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function confirm() {
    setBusy(true)
    setError(null)
    try {
      await onApprove()
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not approve this version')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Approve version ${version}?`}
      description="Approving tells everyone this is the version to build from."
      footer={
        <>
          {openGaps > 0 && (
            <Button variant="ghost" onClick={onReviewGaps} disabled={busy}>
              Review gaps first
            </Button>
          )}
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button variant="primary" icon="check" loading={busy} onClick={confirm}>
            {openGaps > 0 ? 'Approve anyway' : 'Approve this version'}
          </Button>
        </>
      }
    >
      <ul className="approve-points">
        <li>
          <Icon name="lock" size={18} />
          <span>
            <strong>The stories are locked.</strong> Designs are checked against this exact version, so they can’t
            drift.
          </span>
        </li>
        <li>
          <Icon name="layout" size={18} />
          <span>
            <strong>Design unlocks.</strong> Prompts for Figma and the design check are built from this version.
          </span>
        </li>
        <li>
          <Icon name="edit" size={18} />
          <span>
            <strong>Changing it later is fine.</strong> Editing an approved story creates version {version + 1} as a
            new draft — what you approved stays untouched.
          </span>
        </li>
      </ul>

      {openGaps > 0 && (
        <Banner tone="warning">
          <strong>{plural(openGaps, 'gap')} still open.</strong> You can approve with open gaps, but the design may be
          missing the behaviour they describe.
        </Banner>
      )}
      {error && <Banner tone="danger">{error}</Banner>}
    </Modal>
  )
}
