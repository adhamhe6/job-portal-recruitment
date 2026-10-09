import { FileText } from 'lucide-react'
import { Link } from 'react-router-dom'
import { PageHeader } from '@/components/common/PageHeader'
import { ErrorState } from '@/components/common/States'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { dates } from '@/lib/format'
import { paths } from '@/routes/paths'
import { useProfile } from '../api/profile'
import type { CandidateProfile } from '../lib/types'
import { BasicsForm } from '../components/BasicsForm'
import { CompletionCard } from '../components/CompletionCard'
import {
  CertificationSection,
  EducationSection,
  ExperienceSection,
  LanguageSection,
} from '../components/EntrySections'
import { SkillsSection } from '../components/SkillsSection'

function ProfileSkeleton() {
  return (
    <div
      className="grid gap-6 lg:grid-cols-[1fr_20rem]"
      role="status"
      aria-busy="true"
      aria-label="Loading profile"
    >
      <div className="grid gap-6">
        {[0, 1, 2].map((i) => (
          <Card key={i}>
            <CardHeader>
              <Skeleton className="h-5 w-40" />
            </CardHeader>
            <CardContent className="grid gap-3">
              <Skeleton className="h-9 w-full" />
              <Skeleton className="h-9 w-full" />
              <Skeleton className="h-24 w-full" />
            </CardContent>
          </Card>
        ))}
      </div>
      <Skeleton className="h-72 rounded-xl" />
    </div>
  )
}

export default function ProfilePage() {
  useDocumentTitle('My profile')
  const query = useProfile()

  return (
    <>
      <PageHeader
        title="My profile"
        description="Keep your details current — they power your job matches and what recruiters see."
        actions={
          <Button asChild variant="outline">
            <Link to={paths.resume}>
              <FileText /> Manage résumé
            </Link>
          </Button>
        }
        meta={
          query.data ? (
            <span className="text-xs text-muted-foreground">
              Last updated {dates.relative(query.data.updated_at)}
            </span>
          ) : undefined
        }
      />
      {query.isPending ? (
        <ProfileSkeleton />
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={() => query.refetch()} title="Couldn't load your profile" />
      ) : (
        <ProfileContent profile={query.data} />
      )}
    </>
  )
}

function ProfileContent({ profile }: { profile: CandidateProfile }) {
  return (
    <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
      <div className="order-2 grid gap-6 lg:order-1">
        {/* key: re-seed the form when the server copy changes (e.g. after a résumé import) */}
        <BasicsForm key={profile.updated_at} profile={profile} />
        <SkillsSection items={profile.skills} />
        <ExperienceSection items={profile.experiences} />
        <EducationSection items={profile.educations} />
        <CertificationSection items={profile.certifications} />
        <LanguageSection items={profile.languages} />
      </div>
      <div className="order-1 lg:sticky lg:top-20 lg:order-2">
        <CompletionCard completion={profile.completion} />
      </div>
    </div>
  )
}
