/**
 * Plain inline SVG rather than the 🗑️ emoji — emoji glyph rendering is
 * font/OS-dependent and came out as a thin, hard-to-read outline on at
 * least one real system (confirmed directly from a user screenshot).
 * `currentColor` means it inherits whatever color the button/wrapper sets,
 * so visibility is controlled by CSS instead of hoping a given system's
 * emoji font renders clearly.
 */
export function TrashIcon({ size = 14 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <polyline points="3 6 5 6 21 6" />
      <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
      <line x1="10" y1="11" x2="10" y2="17" />
      <line x1="14" y1="11" x2="14" y2="17" />
    </svg>
  )
}
