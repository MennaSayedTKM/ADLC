/**
 * Plain inline SVG (a document with a pencil overlay) rather than an emoji
 * like 📎 — emoji glyph rendering is font/OS-dependent (see TrashIcon.tsx
 * for the same issue confirmed directly from a user screenshot).
 * `currentColor` means it inherits whatever color the trigger button sets.
 */
export function CrDocumentIcon({ size = 14 }: { size?: number }) {
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
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <path d="M12.5 13.5l3 3L11 21l-3.5.5.5-3.5z" />
    </svg>
  )
}
