import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { UxPrompt, UxPromptSources } from '../api/types'
import { UxPromptCard } from '../components/UxPromptCard'
import { UxPromptGenerator } from '../components/UxPromptGenerator'
import { Banner } from '../components/ui/Banner'
import './UxPromptsPage.css'

export function UxPromptsPage({ projectId }: { projectId: string }) {
  const [sources, setSources] = useState<UxPromptSources | null>(null)
  const [prompts, setPrompts] = useState<UxPrompt[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [src, list] = await Promise.all([api.getUxPromptSources(projectId), api.listUxPrompts(projectId)])
      setSources(src)
      setPrompts(list)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load UI/UX prompts')
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => {
    setSources(null)
    setPrompts([])
    load()
  }, [load])

  function handleGenerated(prompt: UxPrompt) {
    setPrompts((prev) => [prompt, ...prev])
    // The suggested mode and saved design system may have changed.
    api.getUxPromptSources(projectId).then(setSources).catch(() => undefined)
  }

  function handleChanged(updated: UxPrompt) {
    setPrompts((prev) => prev.map((p) => (p.id === updated.id ? updated : p)))
  }

  return (
    <div className="ux-page">
      <div className="ux-page__header">
        <h1 className="ux-page__title">UI/UX prompts</h1>
        <p className="ux-page__hint">
          Turn approved user stories into a Figma Make prompt. Paste the prompt into Figma Make to
          generate the screens; developers then use those screens as their build reference. Prompts
          are drafts for you to review and edit, and nothing is sent to Figma from here.
        </p>
      </div>

      {error && <Banner tone="danger">{error}</Banner>}
      {loading && !sources && <p className="ux-page__muted">Loading…</p>}

      {sources && !sources.document && (
        <div className="ux-page__empty">
          <strong>No approved requirements yet.</strong>
          <p>
            Prompts are generated from an approved requirements version, so the stories cannot
            change underneath a design. Approve a version on the Requirements tab, then come back.
          </p>
        </div>
      )}

      {sources?.document && (
        <>
          {sources.epics.length === 0 ? (
            <div className="ux-page__empty">
              <strong>The approved version has no epics.</strong>
            </div>
          ) : (
            <UxPromptGenerator
              key={sources.document.id}
              projectId={projectId}
              sources={sources}
              onGenerated={handleGenerated}
            />
          )}

          {prompts.length > 0 && (
            <section className="ux-page__results">
              <h2 className="ux-page__section-title">Generated prompts</h2>
              {prompts.map((p) => (
                <UxPromptCard
                  key={p.id}
                  projectId={projectId}
                  prompt={p}
                  onChanged={handleChanged}
                  onDeleted={(id) => setPrompts((prev) => prev.filter((x) => x.id !== id))}
                />
              ))}
            </section>
          )}
        </>
      )}
    </div>
  )
}
