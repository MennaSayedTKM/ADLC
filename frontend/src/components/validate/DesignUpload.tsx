import { useElapsed } from '../../lib/useElapsed'
import type { GenerationState } from '../../state/ProjectContext'
import { Banner } from '../ui/Banner'
import { Button } from '../ui/Button'
import { DropTarget } from '../ui/DropTarget'
import { Icon } from '../ui/Icon'
import { IndeterminateBar } from '../ui/Progress'
import './DesignUpload.css'

const DESIGN_ACCEPT = '.pdf,.png,.jpg,.jpeg,.webp,.bmp,.tiff'

interface DesignUploadProps {
  validation: GenerationState
  requirementsVersion: number
  onFile: (file: File) => void
  onDismissError: () => void
}

export function DesignUpload({ validation, requirementsVersion, onFile, onDismissError }: DesignUploadProps) {
  const running = validation.status === 'running'
  const elapsed = useElapsed(validation.status === 'running' ? validation.startedAt : null)

  return (
    <div className="design-upload">
      {validation.status === 'failed' && (
        <Banner
          tone="danger"
          action={
            <Button size="sm" variant="secondary" onClick={onDismissError}>
              Dismiss
            </Button>
          }
        >
          <strong>We couldn’t check the design.</strong> {validation.error}
          <br />
          Nothing was changed — try the upload again.
        </Banner>
      )}

      <DropTarget onFiles={(files) => onFile(files[0])} accept={DESIGN_ACCEPT} multiple={false} disabled={running} className="design-upload__drop">
        {({ open }) => (
          <div className="design-upload__inner">
            <span className="design-upload__icon" aria-hidden="true">
              <Icon name="image" size={28} />
            </span>
            {running ? (
              <div className="design-upload__running" role="status" aria-live="polite">
                <IndeterminateBar label="Checking the design" />
                <p>
                  <strong>Checking each screen against version {requirementsVersion}…</strong> {elapsed}
                </p>
                <p className="design-upload__hint">
                  This takes a minute or two per few screens. You can leave this page — we’ll keep checking.
                </p>
              </div>
            ) : (
              <>
                <h2 className="design-upload__title">Check a design against your requirements</h2>
                <p className="design-upload__body">
                  Upload screens exported from Figma (PDF or image). We’ll tell you which stories each screen covers and
                  where it falls short of version {requirementsVersion}.
                </p>
                <Button variant="primary" size="lg" icon="upload" onClick={open}>
                  Upload your screens
                </Button>
                <p className="design-upload__hint">or drop a PDF or image here</p>
              </>
            )}
          </div>
        )}
      </DropTarget>
    </div>
  )
}
