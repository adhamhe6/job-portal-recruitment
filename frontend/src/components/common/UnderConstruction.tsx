import { Hammer } from 'lucide-react'
import { PageHeader, type Crumb } from './PageHeader'
import { EmptyState } from './States'
import { Card } from '@/components/ui/card'

/**
 * Honest placeholder for feature areas that are not built yet. Wave-2 engineers replace the page module that renders this;
 * the route, navigation and guards already exist and must not need to change.
 */
export function UnderConstruction({
  title,
  description,
  breadcrumbs,
  endpoints,
}: {
  title: string
  description: string
  breadcrumbs?: Crumb[]
  /** Planned API surface, shown for developers. */
  endpoints?: string[]
}) {
  return (
    <>
      <PageHeader title={title} description={description} breadcrumbs={breadcrumbs} />
      <Card>
        <EmptyState
          icon={<Hammer aria-hidden />}
          title="This page is under construction"
          description="We're still building this part of TalentLens. Everything else in your workspace works as usual."
        />
        {endpoints && endpoints.length > 0 && (
          <p className="border-t px-6 py-3 text-center text-xs text-muted-foreground">
            Planned data sources: <code className="font-mono">{endpoints.join(' · ')}</code>
          </p>
        )}
      </Card>
    </>
  )
}
