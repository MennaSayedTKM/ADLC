const isApple = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/i.test(navigator.platform || navigator.userAgent)

/** The key combination that opens search, spelled the way this person's keyboard labels it. */
export const SEARCH_SHORTCUT = isApple ? '⌘K' : 'Ctrl K'
