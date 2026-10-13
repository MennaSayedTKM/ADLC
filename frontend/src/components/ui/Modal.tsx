import { useEffect, useId, useRef, type ReactNode } from 'react'
import { Icon } from './Icon'
import './Modal.css'

interface ModalProps {
  open: boolean
  onClose: () => void
  title: string
  description?: string
  /** `drawer` slides in from the right and suits long, scrollable content. */
  variant?: 'dialog' | 'drawer'
  children: ReactNode
  footer?: ReactNode
}

/**
 * Built on the native <dialog> element so focus is trapped, Escape closes it
 * and the page behind becomes inert without any extra code.
 */
export function Modal({ open, onClose, title, description, variant = 'dialog', children, footer }: ModalProps) {
  const ref = useRef<HTMLDialogElement>(null)
  const titleId = useId()

  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (open && !dialog.open) dialog.showModal()
    if (!open && dialog.open) dialog.close()
  }, [open])

  return (
    <dialog
      ref={ref}
      className={`modal modal--${variant}`}
      aria-labelledby={titleId}
      onClose={onClose}
      onClick={(e) => {
        // A click on the backdrop lands on the <dialog> element itself.
        if (e.target === e.currentTarget) onClose()
      }}
    >
      {open && (
        <div className="modal__panel">
          <header className="modal__header">
            <div>
              <h2 id={titleId} className="modal__title">
                {title}
              </h2>
              {description && <p className="modal__description">{description}</p>}
            </div>
            <button type="button" className="modal__close" onClick={onClose} aria-label="Close">
              <Icon name="x" size={18} />
            </button>
          </header>
          <div className="modal__body">{children}</div>
          {footer && <footer className="modal__footer">{footer}</footer>}
        </div>
      )}
    </dialog>
  )
}
