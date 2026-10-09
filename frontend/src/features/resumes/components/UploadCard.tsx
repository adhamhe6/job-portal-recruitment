import { useState } from 'react'
import { toast } from 'sonner'
import { FileDropzone } from '@/components/common/FileDropzone'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { ApiError } from '@/lib/api'
import { useUploadResume, type ResumeUploadOut } from '../api/resumes'

/** Backend limit (settings.max_resume_mb); the server re-validates content type by magic bytes. */
export const MAX_RESUME_MB = 5
export const RESUME_EXTENSIONS = ['.pdf', '.docx']

export function uploadErrorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    switch (e.code) {
      case 'PAYLOAD_TOO_LARGE':
        return `That file is larger than ${MAX_RESUME_MB} MB. Compress it or export a smaller PDF and try again.`
      case 'UNSUPPORTED_MEDIA_TYPE':
        return 'Only PDF and Word (.docx) résumés are supported. Legacy .doc files must be re-saved as .docx or PDF.'
      case 'RATE_LIMITED':
        return 'You are uploading too quickly. Wait a minute and try again.'
      default:
        if (e.status === 422)
          return e.fieldIssues[0]?.message ?? 'That file could not be read. Is it empty or damaged?'
        return e.message
    }
  }
  return 'The upload failed. Check your connection and try again.'
}

export function UploadCard({
  hasResumes,
  onUploaded,
}: {
  hasResumes: boolean
  onUploaded?: (r: ResumeUploadOut) => void
}) {
  const upload = useUploadResume()
  const [file, setFile] = useState<File | null>(null)
  const [progress, setProgress] = useState<number | null>(null)
  const [setPrimary, setSetPrimary] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const submit = async () => {
    if (!file) return
    setError(null)
    setProgress(0)
    try {
      const res = await upload.mutateAsync({
        file,
        setPrimary: setPrimary || !hasResumes,
        onProgress: setProgress,
      })
      setFile(null)
      if (res.duplicate) {
        toast.info('You already uploaded this exact file', { description: res.original_filename })
      } else if (res.message) {
        toast.warning('Uploaded, but processing has not started', { description: res.message })
      } else {
        toast.success('Résumé uploaded', {
          description: 'We are reading it now — this usually takes a few seconds.',
        })
      }
      onUploaded?.(res)
    } catch (e) {
      setError(uploadErrorMessage(e))
    } finally {
      setProgress(null)
    }
  }

  return (
    <Card aria-labelledby="upload-title">
      <CardHeader>
        <CardTitle id="upload-title" className="text-lg">
          Upload a résumé
        </CardTitle>
        <CardDescription>
          PDF or Word (.docx), up to {MAX_RESUME_MB} MB. We extract your skills and experience as suggestions
          you can review — nothing is added to your profile automatically.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        {error && <Alert variant="danger">{error}</Alert>}
        <FileDropzone
          accept={RESUME_EXTENSIONS}
          maxSizeMB={MAX_RESUME_MB}
          file={file}
          onFile={(f) => {
            setError(null)
            setFile(f)
          }}
          onClear={() => setFile(null)}
          progress={progress}
          disabled={upload.isPending}
          title="Drop your résumé here, or click to browse"
        />
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Checkbox
              id="set-primary"
              checked={setPrimary || !hasResumes}
              disabled={!hasResumes}
              onCheckedChange={(c) => setSetPrimary(c === true)}
            />
            <Label htmlFor="set-primary">Use as my primary résumé</Label>
          </div>
          <Button onClick={submit} disabled={!file} loading={upload.isPending}>
            Upload résumé
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
