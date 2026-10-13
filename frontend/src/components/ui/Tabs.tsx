import { useRef, type KeyboardEvent, type ReactNode } from 'react'
import './Tabs.css'

export interface TabItem<T extends string> {
  id: T
  label: string
  count?: number
  /** Count rendered as a warning (e.g. open gaps). */
  alert?: boolean
}

interface TabsProps<T extends string> {
  tabs: TabItem<T>[]
  active: T
  onChange: (id: T) => void
  label: string
  trailing?: ReactNode
}

export function Tabs<T extends string>({ tabs, active, onChange, label, trailing }: TabsProps<T>) {
  const listRef = useRef<HTMLDivElement>(null)

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    const index = tabs.findIndex((t) => t.id === active)
    let next = index
    if (e.key === 'ArrowRight') next = (index + 1) % tabs.length
    else if (e.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length
    else if (e.key === 'Home') next = 0
    else if (e.key === 'End') next = tabs.length - 1
    else return
    e.preventDefault()
    onChange(tabs[next].id)
    listRef.current?.querySelectorAll<HTMLButtonElement>('[role="tab"]')[next]?.focus()
  }

  return (
    <div className="tabs">
      <div className="tabs__list" role="tablist" aria-label={label} ref={listRef} onKeyDown={onKeyDown}>
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            id={`tab-${tab.id}`}
            aria-selected={tab.id === active}
            aria-controls={`panel-${tab.id}`}
            tabIndex={tab.id === active ? 0 : -1}
            className={`tabs__tab ${tab.id === active ? 'tabs__tab--active' : ''}`}
            onClick={() => onChange(tab.id)}
          >
            {tab.label}
            {tab.count !== undefined && (
              <span className={`tabs__count ${tab.alert ? 'tabs__count--alert' : ''}`}>{tab.count}</span>
            )}
          </button>
        ))}
      </div>
      {trailing && <div className="tabs__trailing">{trailing}</div>}
    </div>
  )
}

export function TabPanel({ id, active, children }: { id: string; active: boolean; children: ReactNode }) {
  if (!active) return null
  return (
    <div role="tabpanel" id={`panel-${id}`} aria-labelledby={`tab-${id}`}>
      {children}
    </div>
  )
}
