import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { UxPrompt, UxPromptSources } from '../api/types'
import { UxBlueprintPanel } from '../components/UxBlueprintPanel'
import { UxFeaturePanel } from '../components/UxFeaturePanel'
import { UxPromptCard } from '../components/UxPromptCard'
import { Banner } from '../components/ui/Banner'
import './UxPromptsPage.css'

export function UxPromptsPage({ projectId }: { projectId: string }) {
  const [sources, setSources] = useState<UxPromptSources | null>(null)
  const [prompts, setPrompts] = useState<UxPrompt[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const refreshSources = useCallback(
    () => api.getUxPromptSources(projectId).then(setSources).catch(() => undefined),
    [projectId],
  )

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

  // The blueprint is created or regenerated in place; features are always new rows.
  function handleBlueprint(prompt: UxPrompt) {
    setPrompts((prev) => (prev.some((p) => p.id === prompt.id) ? prev.map((p) => (p.id === prompt.id ? prompt : p)) : [prompt, ...prev]))
    refreshSources()
  }

  function handleFeature(prompt: UxPrompt) {
    setPrompts((prev) => [...prev, prompt])
  }

  function handleChanged(updated: UxPrompt) {
    setPrompts((prev) => prev.map((p) => (p.id === updated.id ? updated : p)))
    if (updated.mode === 'foundation' || updated.screens.length > 0) refreshSources()
  }

  const blueprint = prompts.find((p) => p.mode === 'foundation')
  // Oldest first: that is the order the PM pastes them into Figma Make.
  const features = prompts
    .filter((p) => p.mode !== 'foundation')
    .sort((a, b) => a.created_at.localeCompare(b.created_at))

  return (
    <div className="ux-page">
      <div className="ux-page__header">
        <h1 className="ux-page__title">UI/UX prompts</h1>
        <p className="ux-page__hint">
          Turn approved user stories into Figma Make prompts, built like blocks: first a blueprint for the whole
          platform, then one prompt per feature that fits into it. Paste them into the same Figma Make project, in
          order, so the screens stay consistent. Prompts are drafts for you to review and edit; nothing is sent to
          Figma from here.
        </p>
      </div>

      {error && <Banner tone="danger">{error}</Banner>}
      {loading && !sources && <p className="ux-page__muted">Loading…</p>}

      {sources && !sources.document && (
        <div className="ux-page__empty">
          <strong>No approved requirements yet.</strong>
          <p>
            Prompts are generated from an approved requirements version, so the stories cannot change underneath a
            design. Approve a version on the Requirements tab, then come back.
          </p>
        </div>
      )}

      {sources?.document && sources.epics.length === 0 && (
        <div className="ux-page__empty">
          <strong>The approved version has no epics.</strong>
        </div>
      )}

      {sources?.document && sources.epics.length > 0 && (
        <>
          <UxBlueprintPanel
            key={`${sources.document.id}-${sources.blueprint_prompt_id ?? 'none'}`}
            projectId={projectId}
            sources={sources}
            onBlueprint={handleBlueprint}
          />
          <UxFeaturePanel
            key={sources.document.id}
            projectId={projectId}
            sources={sources}
            onPrompt={handleFeature}
            onFinished={refreshSources}
          />
        </>
      )}

      {prompts.length > 0 && (
        <section className="ux-page__results">
          <h2 className="ux-page__section-title">Generated prompts</h2>
          {[...(blueprint ? [blueprint] : []), ...features].map((p) => (
            <UxPromptCard
              key={`${p.id}-${p.updated_at}`}
              projectId={projectId}
              prompt={p}
              onChanged={handleChanged}
              onDeleted={(id) => {
                setPrompts((prev) => prev.filter((x) => x.id !== id))
                refreshSources()
              }}
            />
          ))}
        </section>
      )}
    </div>
  )
}
