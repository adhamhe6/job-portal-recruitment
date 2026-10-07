import { Compass } from 'lucide-react'
import { Link } from 'react-router-dom'
import { EmptyState } from '@/components/common/States'
import { PageContainer } from '@/components/layout/PageContainer'
import { Button } from '@/components/ui/button'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { paths } from '@/routes/paths'

export default function NotFoundPage() {
  useDocumentTitle('Page not found')
  return (
    <PageContainer>
    <div className="mx-auto max-w-lg py-12">
      <EmptyState
        icon={<Compass aria-hidden />}
        title="Page not found"
        description="The page you are looking for doesn't exist or has moved."
        action={
          <>
            <Button asChild>
              <Link to={paths.home}>Back to home</Link>
            </Button>
            <Button asChild variant="outline">
              <Link to={paths.jobs}>Browse jobs</Link>
            </Button>
          </>
        }
      />
    </div>
    </PageContainer>
  )
}
