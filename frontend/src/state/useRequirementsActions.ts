import { useState } from 'react'
import { api } from '../api/client'
import type { ChangeRequestIngestResponse, ItemFields, RequirementsDetail } from '../api/types'
import { useProject } from './ProjectContext'

/**
 * Every edit to the requirements goes through here, so the review page, the
 * suggestions panel and the gap panel stay in step. Editing an approved
 * version forks a new draft on the server; `forkNotice` tells the person that
 * happened instead of silently showing different content.
 */
export function useRequirementsActions() {
  const { project, requirements, setRequirements, reloadRequirements } = useProject()
  const [forkNotice, setForkNotice] = useState<string | null>(null)
  const projectId = project.id

  function applyUpdate(previousDocId: string, updated: RequirementsDetail, forkedActionLabel: string) {
    if (updated.document.id !== previousDocId) {
      setForkNotice(
        `That version was already approved, so ${forkedActionLabel} created version ${updated.document.version} instead of changing what was approved.`,
      )
    } else {
      setForkNotice(null)
    }
    setRequirements(updated)
  }

  function current() {
    if (!requirements) throw new Error('There are no requirements to change yet')
    return requirements
  }

  return {
    forkNotice,
    clearForkNotice: () => setForkNotice(null),

    async saveItem(itemId: string, fields: ItemFields) {
      const previous = current().document.id
      applyUpdate(previous, await api.updateItem(projectId, previous, itemId, fields), 'your edit')
    },

    async createEpic(text: string, fields?: ItemFields) {
      const previous = current().document.id
      applyUpdate(previous, await api.createItem(projectId, previous, { type: 'epic', text, ...fields }), 'adding this epic')
    },

    async createStory(parentId: string, fields: ItemFields & { text: string }) {
      const previous = current().document.id
      applyUpdate(
        previous,
        await api.createItem(projectId, previous, { type: 'story', parent_id: parentId, ...fields }),
        'adding this story',
      )
    },

    async deleteItem(itemId: string) {
      const previous = current().document.id
      applyUpdate(previous, await api.deleteItem(projectId, previous, itemId), 'deleting this item')
    },

    async setGapStatus(gapId: string, status: 'dismissed' | 'open') {
      setRequirements(await api.updateGapStatus(projectId, current().document.id, gapId, status))
    },

    async resolveGapAsStory(gapId: string, parentId: string, fields?: ItemFields) {
      const previous = current().document.id
      applyUpdate(
        previous,
        await api.resolveGapAsStory(projectId, previous, gapId, { parent_id: parentId, ...fields }),
        'resolving this gap',
      )
    },

    async acceptSuggestion(itemId: string) {
      const previous = current().document.id
      applyUpdate(previous, await api.acceptSuggestion(projectId, previous, itemId), 'accepting this suggestion')
    },

    async dismissSuggestion(itemId: string) {
      const previous = current().document.id
      applyUpdate(previous, await api.dismissSuggestion(projectId, previous, itemId), 'dismissing this suggestion')
    },

    async approve() {
      await api.approve(projectId, current().document.id)
      await reloadRequirements()
    },

    /** Evaluation never forks a version. */
    async runEvaluation() {
      setRequirements(await api.runEvaluation(projectId, current().document.id))
    },

    async changeRequestFiled(result: ChangeRequestIngestResponse) {
      const previous = current().document.id
      applyUpdate(previous, await api.getRequirementsVersion(projectId, result.requirements_document.id), 'filing this change request')
    },
  }
}
