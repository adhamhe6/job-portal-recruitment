import { Download, FileText } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { ApiError, downloadFile, errorMessage } from '@/lib/api'

/** Authenticated résumé download (GET /resumes/{id}/file). A 403/404 is explained instead of failing silently. */
export function ResumeButton({ resumeId, filename }: { resumeId: string | null; filename?: string | null }) {
  const [busy, setBusy] = useState(false)
  if (!resumeId)
    return (
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <FileText className="size-4" aria-hidden /> No résumé attached
      </p>
    )

  const download = async () => {
    setBusy(true)
    try {
      await downloadFile(`/resumes/${resumeId}/file`, undefined, filename ?? 'resume')
    } catch (e) {
      toast.error("Couldn't download the résumé", {
        description:
          e instanceof ApiError && (e.status === 403 || e.status === 404)
            ? "You don't have access to this résumé, or the file is no longer available."
            : errorMessage(e),
      })
    } finally {
      setBusy(false)
    }
  }

  return (
    <Button variant="outline" size="sm" onClick={() => void download()} loading={busy}>
      <Download /> {filename ? `Download ${filename}` : 'Download résumé'}
    </Button>
  )
}
