import { UnderConstruction } from '@/components/common/UnderConstruction'

/** WAVE 2: replace this placeholder with the real page (keep the default export; the route already points here). */
export default function ResumePage() {
  return (
    <UnderConstruction
      title="Résumé"
      description="Upload your résumé and review what we extracted from it."
      endpoints={['GET /resumes', 'POST /resumes']}
    />
  )
}
