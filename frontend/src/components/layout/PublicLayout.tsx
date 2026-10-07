import { Menu } from 'lucide-react'
import { useState } from 'react'
import { Link, NavLink, Outlet } from 'react-router-dom'
import { Logo } from '@/components/common/Logo'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetTitle, SheetTrigger } from '@/components/ui/sheet'
import { useAuth } from '@/features/auth/hooks/useAuth'
import { cn } from '@/lib/utils'
import { paths } from '@/routes/paths'
import { LayoutKindContext } from './PageContainer'
import { SkipLink, useFocusMainOnNavigate } from './RouteFocus'
import { ThemeToggle } from './ThemeToggle'

const linkClass = ({ isActive }: { isActive: boolean }) =>
  cn('rounded-md px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground', isActive && 'text-foreground')

/** Logged-out layout: marketing header + footer around public pages (landing, job search, job detail). */
export function PublicLayout() {
  const { status } = useAuth()
  const signedIn = status === 'authenticated'
  const [open, setOpen] = useState(false)
  useFocusMainOnNavigate()

  const nav = (
    <>
      <NavLink to={paths.jobs} end className={linkClass} onClick={() => setOpen(false)}>
        Find jobs
      </NavLink>
      <NavLink to={paths.registerEmployer} className={linkClass} onClick={() => setOpen(false)}>
        For employers
      </NavLink>
    </>
  )

  return (
    <div className="flex min-h-dvh flex-col bg-background">
      <SkipLink />
      <header className="sticky top-0 z-20 border-b bg-background/85 backdrop-blur-md">
        <div className="mx-auto flex h-16 max-w-7xl items-center gap-4 px-4 sm:px-6 lg:px-8">
          <Link to={paths.home} aria-label="TalentLens home" className="rounded-md">
            <Logo />
          </Link>
          <nav aria-label="Main" className="ml-6 hidden items-center gap-1 md:flex">
            {nav}
          </nav>
          <div className="ml-auto flex items-center gap-1.5 sm:gap-2">
            <ThemeToggle />
            {signedIn ? (
              <Button asChild>
                <Link to={paths.dashboard}>Dashboard</Link>
              </Button>
            ) : (
              <>
                <Button asChild variant="ghost" className="hidden sm:inline-flex">
                  <Link to={paths.login}>Sign in</Link>
                </Button>
                <Button asChild>
                  <Link to={paths.register}>Get started</Link>
                </Button>
              </>
            )}
            <Sheet open={open} onOpenChange={setOpen}>
              <SheetTrigger asChild>
                <Button variant="ghost" size="icon" className="md:hidden" aria-label="Open menu">
                  <Menu />
                </Button>
              </SheetTrigger>
              <SheetContent side="right" aria-describedby={undefined}>
                <SheetTitle className="border-b px-5 py-4 text-base font-semibold">Menu</SheetTitle>
                <SheetDescription className="sr-only">Site navigation</SheetDescription>
                <nav aria-label="Mobile" className="flex flex-col gap-1 px-3 [&_a]:py-2.5 [&_a]:text-base">
                  {nav}
                  {!signedIn && (
                    <NavLink to={paths.login} className={linkClass} onClick={() => setOpen(false)}>
                      Sign in
                    </NavLink>
                  )}
                </nav>
              </SheetContent>
            </Sheet>
          </div>
        </div>
      </header>

      <main id="main-content" tabIndex={-1} className="flex-1 outline-none">
        <LayoutKindContext.Provider value="public">
          <Outlet />
        </LayoutKindContext.Provider>
      </main>

      <footer className="border-t bg-card">
        <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-3 px-4 py-6 text-sm text-muted-foreground sm:flex-row sm:px-6 lg:px-8">
          <Logo className="[&>span:last-child]:text-sm" />
          <p>© {new Date().getFullYear()} TalentLens. Explainable matching for fairer hiring.</p>
          <nav aria-label="Footer" className="flex gap-4">
            <Link to={paths.jobs} className="hover:text-foreground">
              Find jobs
            </Link>
            <Link to={paths.registerEmployer} className="hover:text-foreground">
              Post a job
            </Link>
          </nav>
        </div>
      </footer>
    </div>
  )
}
