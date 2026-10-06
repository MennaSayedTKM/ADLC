import { useState } from 'react'
import { api } from '../api/client'
import type { ReferenceStyle, StyleTags } from '../api/types'
import { Button } from './ui/Button'
import { Banner } from './ui/Banner'
import './StyleReferenceEditor.css'

interface Props {
  projectId: string
  references: ReferenceStyle[]
  onChange: (references: ReferenceStyle[]) => void
  disabled?: boolean
}

type TagList = 'fonts' | 'radii' | 'shadows'

export function StyleReferenceEditor({ projectId, references, onChange, disabled }: Props) {
  const [url, setUrl] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault()
    if (!url.trim()) return
    setBusy(true)
    setError(null)
    try {
      const reference = await api.extractStyleReference(projectId, url.trim())
      onChange([...references, { ...reference, note: note.trim() || null }])
      setUrl('')
      setNote('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not read that website')
    } finally {
      setBusy(false)
    }
  }

  function update(index: number, tags: StyleTags) {
    onChange(references.map((r, i) => (i === index ? { ...r, style_tags: tags } : r)))
  }

  function removeColor(index: number, hex: string) {
    const tags = references[index].style_tags
    update(index, { ...tags, palette: (tags.palette ?? []).filter((p) => p.hex !== hex) })
  }

  function removeTag(index: number, list: TagList, value: string) {
    const tags = references[index].style_tags
    update(index, { ...tags, [list]: (tags[list] ?? []).filter((v) => v !== value) })
  }

  return (
    <div className="style-refs">
      <form className="style-refs__add" onSubmit={handleAdd}>
        <div className="style-refs__add-fields">
          <label className="style-refs__field style-refs__field--url">
            <span className="style-refs__label">Reference website</span>
            <input
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://www.apple.com"
              disabled={disabled || busy}
            />
          </label>
          <label className="style-refs__field">
            <span className="style-refs__label">What to take from it</span>
            <input
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="overall feel, navigation, cards…"
              disabled={disabled || busy}
            />
          </label>
          <Button type="submit" variant="secondary" disabled={disabled || busy || !url.trim()}>
            {busy ? 'Reading site…' : 'Extract style'}
          </Button>
        </div>
        <p className="style-refs__hint">
          The server reads the page&rsquo;s public HTML and CSS (colors, fonts, radii, shadows). Sites that
          style themselves with JavaScript give fewer results, so add a note in the brief too.
        </p>
      </form>

      {error && <Banner tone="danger">{error}</Banner>}

      {references.map((ref, index) => {
        const tags = ref.style_tags
        const fonts = [...(tags.fonts ?? []), ...(tags.google_fonts ?? []).filter((f) => !(tags.fonts ?? []).includes(f))]
        return (
          <article key={`${ref.url}-${index}`} className="style-ref">
            <header className="style-ref__header">
              <div>
                <div className="style-ref__title">{ref.title || ref.url}</div>
                <div className="style-ref__meta">
                  {ref.url}
                  {ref.note ? ` · ${ref.note}` : ''}
                </div>
              </div>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                onClick={() => onChange(references.filter((_, i) => i !== index))}
                disabled={disabled}
              >
                Remove site
              </Button>
            </header>

            {ref.notes?.map((n) => (
              <Banner key={n} tone="warning">
                {n}
              </Banner>
            ))}

            {(tags.palette?.length ?? 0) > 0 && (
              <div className="style-ref__row">
                <span className="style-ref__row-label">Colors</span>
                <div className="style-ref__chips">
                  {tags.palette!.map((c) => (
                    <button
                      key={c.hex}
                      type="button"
                      className="style-ref__swatch"
                      title={`Remove ${c.hex}`}
                      aria-label={`Remove color ${c.hex}`}
                      onClick={() => removeColor(index, c.hex)}
                      disabled={disabled}
                    >
                      <span className="style-ref__dot" style={{ background: c.hex }} />
                      {c.hex}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {(['fonts', 'radii', 'shadows'] as TagList[]).map((list) => {
              const values = list === 'fonts' ? fonts : (tags[list] ?? [])
              if (values.length === 0) return null
              return (
                <div className="style-ref__row" key={list}>
                  <span className="style-ref__row-label">{list === 'fonts' ? 'Fonts' : list === 'radii' ? 'Corner radii' : 'Shadows'}</span>
                  <div className="style-ref__chips">
                    {values.map((v) => (
                      <button
                        key={v}
                        type="button"
                        className="style-ref__chip"
                        title={`Remove ${v}`}
                        aria-label={`Remove ${v}`}
                        onClick={() => removeTag(index, list, v)}
                        disabled={disabled}
                      >
                        {v.length > 48 ? `${v.slice(0, 48)}…` : v}
                      </button>
                    ))}
                  </div>
                </div>
              )
            })}

            {(tags.font_sizes_px?.length ?? 0) > 0 && (
              <div className="style-ref__row">
                <span className="style-ref__row-label">Type sizes</span>
                <span className="style-ref__plain">{tags.font_sizes_px!.map((s) => `${s}px`).join(' · ')}</span>
              </div>
            )}
          </article>
        )
      })}
    </div>
  )
}
