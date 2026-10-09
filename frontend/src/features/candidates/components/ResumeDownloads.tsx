import { Download, FileText } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { StatusBadge } from '@/components/common/StatusBadge'
import { Button } from '@/components/ui/button'
import { downloadFile, errorMessage } from '@/lib/api'
import { dates } from '@/lib/format'
import type { ResumeBrief } from '../api/candidates'
import { resumeFileName } from '../lib/profile'

/** Download buttons for the résumés the API released (access = FULL). Each download re-checks authorization server-side. */
export function ResumeDownloads({
  resumes,
  candidateName,
}: {
  resumes: ResumeBrief[]
  candidateName: string
}) {
  const [busyId, setBusyId] = useState<string | null>(null)
  const download = async (r: ResumeBrief) => {
    setBusyId(r.id)
    try {
      await downloadFile(`/resumes/${r.id}/file`, undefined, resumeFileName(r, candidateName))
    } catch (e) {
      toast.error('Couldn’t download the résumé', { description: errorMessage(e) })
    } finally {
      setBusyId(null)
    }
  }
  return (
    <ul className="space-y-2" aria-label="Résumés">
      {resumes.map((r) => (
        <li key={r.id} className="flex items-center gap-2.5 rounded-lg border p-2.5">
          <FileText className="size-4 shrink-0 text-muted-foreground" aria-hidden />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium" title={r.original_filename ?? undefined}>
              {r.original_filename ?? 'Résumé'}
            </p>
            <p className="flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
              {dates.date(r.created_at)}
              {r.is_primary && <span className="font-medium text-foreground">Primary</span>}
              <StatusBadge kind="resume" status={r.status} />
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            loading={busyId === r.id}
            onClick={() => void download(r)}
            aria-label={`Download ${r.original_filename ?? 'résumé'}`}
          >
            <Download /> Download
          </Button>
        </li>
      ))}
    </ul>
  )
}
