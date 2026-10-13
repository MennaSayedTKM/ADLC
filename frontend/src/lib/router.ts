import { useSyncExternalStore } from 'react'

/**
 * Hash routing, so deep links and the back button work without adding a
 * router dependency or any server-side route handling (the production
 * container serves one static index.html).
 *
 *   #/                         Projects home
 *   #/standards                Company standards
 *   #/settings                 Settings
 *   #/p/<id>/<page>?<query>    A page inside a project
 */

export type ProjectPage =
  | 'overview'
  | 'sources'
  | 'requirements'
  | 'design'
  | 'validate'
  | 'publish'
  | 'dev-stories'

const PROJECT_PAGES: ProjectPage[] = [
  'overview',
  'sources',
  'requirements',
  'design',
  'validate',
  'publish',
  'dev-stories',
]

export type Route =
  | { name: 'home' }
  | { name: 'standards' }
  | { name: 'settings' }
  | { name: 'project'; projectId: string; page: ProjectPage; query: URLSearchParams }

export function parseHash(hash: string): Route {
  const raw = hash.replace(/^#/, '')
  const [path, queryString = ''] = raw.split('?')
  const parts = path.split('/').filter(Boolean)

  if (parts[0] === 'standards') return { name: 'standards' }
  if (parts[0] === 'settings') return { name: 'settings' }

  if (parts[0] === 'p' && parts[1]) {
    const requested = parts[2] as ProjectPage | undefined
    const page = requested && PROJECT_PAGES.includes(requested) ? requested : 'overview'
    return { name: 'project', projectId: parts[1], page, query: new URLSearchParams(queryString) }
  }

  return { name: 'home' }
}

export function projectHref(projectId: string, page: ProjectPage = 'overview', query?: Record<string, string>): string {
  const qs = query && Object.keys(query).length > 0 ? `?${new URLSearchParams(query).toString()}` : ''
  return `#/p/${projectId}/${page}${qs}`
}

export const HOME_HREF = '#/'
export const STANDARDS_HREF = '#/standards'
export const SETTINGS_HREF = '#/settings'

export function navigate(href: string) {
  if (window.location.hash === href) {
    window.dispatchEvent(new HashChangeEvent('hashchange'))
    return
  }
  window.location.hash = href
}

// useSyncExternalStore needs a referentially stable snapshot, so the raw hash
// string is the snapshot and parsing happens in the hook.
function subscribe(callback: () => void) {
  window.addEventListener('hashchange', callback)
  return () => window.removeEventListener('hashchange', callback)
}

const getSnapshot = () => window.location.hash

export function useHash(): string {
  return useSyncExternalStore(subscribe, getSnapshot, () => '')
}

export function useRoute(): Route {
  return parseHash(useHash())
}
