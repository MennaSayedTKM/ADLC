import { useCallback, useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { DesignDetail } from '../api/types'
import { DesignHeader } from '../components/DesignHeader'
import { ScreenDetail } from '../components/ScreenDetail'
import { ScreenGrid } from '../components/ScreenGrid'
import { UploadPrompt } from '../components/UploadPrompt'
import { Banner } from '../components/ui/Banner'
import './DesignReviewPage.css'

interface DesignReviewPageProps {
  projectId: string
}

export function DesignReviewPage({ projectId }: DesignReviewPageProps) {
  const [detail, setDetail] = useState<DesignDetail | null | undefined>(undefined)
  const [hasApprovedRequirements, setHasApprovedRequirements] = useState<boolean | undefined>(undefined)
  const [requirementsVersion, setRequirementsVersion] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selectedPage, setSelectedPage] = useState<number | null>(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      const data = await api.getLatestDesign(projectId)
      setDetail(data)
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setDetail(null)
      } else {
        setError(err instanceof Error ? err.message : 'Failed to load design review')
      }
    }
  }, [projectId])

  const checkApprovedRequirements = useCallback(async () => {
    try {
      const data = await api.getLatestRequirements(projectId)
      setHasApprovedRequirements(data.document.approval_status === 'approved')
    } catch {
      setHasApprovedRequirements(false)
    }
  }, [projectId])

  useEffect(() => {
    setDetail(undefined)
    setSelectedPage(null)
    load()
    checkApprovedRequirements()
  }, [projectId, load, checkApprovedRequirements])

  useEffect(() => {
    if (!detail?.requirements_document_id) {
      setRequirementsVersion(null)
      return
    }
    api
      .getRequirementsVersion(projectId, detail.requirements_document_id)
      .then((d) => setRequirementsVersion(d.document.version))
      .catch(() => setRequirementsVersion(null))
  }, [projectId, detail?.requirements_document_id])

  async function handleUpload(file: File) {
    await api.uploadDesign(projectId, file)
    await load()
  }

  async function handleFindingStatus(findingId: string, status: 'resolved' | 'dismissed' | 'open') {
    if (!detail) return
    const updated = await api.updateFindingStatus(projectId, detail.document.id, findingId, status)
    setDetail(updated)
  }

  if (detail === undefined || hasApprovedRequirements === undefined) {
    return <div className="design-page__loading">Loading…</div>
  }

  if (error) {
    return (
      <div className="design-page">
        <Banner tone="danger">{error}</Banner>
      </div>
    )
  }

  if (detail === null) {
    return (
      <div className="design-page">
        <UploadPrompt
          onUpload={handleUpload}
          icon="🖼"
          title="No design screens uploaded yet"
          body="Upload a Figma screen export (PDF or image). Each screen is checked against the approved requirements and given an alignment status with specific findings."
          progressLabel="Rendering screens and running GPT-4o alignment checks…"
          disabled={!hasApprovedRequirements}
          disabledMessage="Approve a requirements version first — design review checks screens against approved requirements, not drafts."
        />
      </div>
    )
  }

  const selectedReport = selectedPage !== null ? detail.reports.find((r) => r.page === selectedPage) : undefined

  return (
    <div className="design-page">
      <DesignHeader
        document={detail.document}
        requirementsVersion={requirementsVersion}
        reports={detail.reports}
      />

      {selectedReport ? (
        <ScreenDetail
          report={selectedReport}
          imageUrl={api.screenImageUrl(projectId, detail.document.id, selectedReport.page)}
          onBack={() => setSelectedPage(null)}
          onSetFindingStatus={handleFindingStatus}
        />
      ) : (
        <ScreenGrid
          reports={detail.reports}
          imageUrl={(page) => api.screenImageUrl(projectId, detail.document.id, page)}
          onSelect={setSelectedPage}
        />
      )}
    </div>
  )
}
