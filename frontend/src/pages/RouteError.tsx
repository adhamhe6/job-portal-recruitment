import { isRouteErrorResponse, useRouteError } from 'react-router-dom'
import { ErrorState } from '@/components/common/States'
import { Button } from '@/components/ui/button'

/** Router errorElement: render errors, failed lazy chunks (e.g. after a deploy) and unexpected throws. */
export default function RouteError() {
  const error = useRouteError()
  const chunkFailed =
    error instanceof Error &&
    /dynamically imported module|Importing a module script failed|Failed to fetch dynamically/i.test(
      error.message,
    )
  const message = isRouteErrorResponse(error)
    ? `${error.status} ${error.statusText}`
    : error instanceof Error
      ? error.message
      : 'Unexpected error'
  return (
    <div className="mx-auto flex min-h-dvh max-w-lg flex-col items-center justify-center p-6">
      <ErrorState
        error={
          new Error(
            chunkFailed ? 'A new version of TalentLens is available. Reload the page to continue.' : message,
          )
        }
        title={chunkFailed ? 'Update available' : 'Something went wrong'}
      />
      <Button onClick={() => window.location.reload()}>Reload page</Button>
    </div>
  )
}
