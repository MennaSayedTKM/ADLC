import { useRef, useState, type ReactNode } from 'react'
import './DropTarget.css'

export const SOURCE_ACCEPT = '.pdf,.docx,.png,.jpg,.jpeg,.webp,.bmp,.tiff'

interface DropTargetProps {
  onFiles: (files: File[]) => void
  accept?: string
  multiple?: boolean
  disabled?: boolean
  className?: string
  /** Receives `open` (shows the file picker) and `dragging` so the layout can react. */
  children: (api: { open: () => void; dragging: boolean }) => ReactNode
}

/**
 * Wraps any layout so it accepts dropped files and can open the native picker.
 * The picker input is real and keyboard-reachable through whatever button the
 * children wire to `open`.
 */
export function DropTarget({ onFiles, accept = SOURCE_ACCEPT, multiple = true, disabled = false, className = '', children }: DropTargetProps) {
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  return (
    <div
      className={`drop-target ${dragging ? 'drop-target--dragging' : ''} ${disabled ? 'drop-target--disabled' : ''} ${className}`.trim()}
      onDragOver={(e) => {
        if (disabled) return
        e.preventDefault()
        setDragging(true)
      }}
      onDragLeave={(e) => {
        // dragleave also fires when moving between child elements
        if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragging(false)
      }}
      onDrop={(e) => {
        e.preventDefault()
        setDragging(false)
        if (disabled) return
        const files = Array.from(e.dataTransfer.files ?? [])
        if (files.length > 0) onFiles(multiple ? files : files.slice(0, 1))
      }}
    >
      {children({ open: () => !disabled && inputRef.current?.click(), dragging })}
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        multiple={multiple}
        hidden
        onChange={(e) => {
          const files = Array.from(e.target.files ?? [])
          if (files.length > 0) onFiles(files)
          e.target.value = ''
        }}
      />
    </div>
  )
}
