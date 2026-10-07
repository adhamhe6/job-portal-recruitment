import { ShieldAlert } from 'lucide-react'
import { Link } from 'react-router-dom'
import { EmptyState } from '@/components/common/States'
import { Button } from '@/components/ui/button'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { paths } from '@/routes/paths'

/** Rendered in place when the signed-in user's role / permissions don't allow the page. */
export default function ForbiddenPage() {
  useDocumentTitle('Access denied')
  return (
    <div className="mx-auto max-w-lg py-16">
      <EmptyState
        icon={<ShieldAlert aria-hidden />}
        title="You don't have access to this page"
        description="Your account's role doesn't include this area. If you think this is a mistake, contact your company administrator."
        action={
          <Button asChild>
            <Link to={paths.dashboard}>Go to my dashboard</Link>
          </Button>
        }
      />
    </div>
  )
}
