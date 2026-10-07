import { Menu } from 'lucide-react'
import { useState } from 'react'
import { Outlet } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetTitle, SheetTrigger } from '@/components/ui/sheet'
import { NotificationBell } from '@/features/notifications/components/NotificationBell'
import { cn } from '@/lib/utils'
import { GlobalSearch } from './GlobalSearch'
import { LayoutKindContext } from './PageContainer'
import { SkipLink, useFocusMainOnNavigate } from './RouteFocus'
import { Sidebar } from './Sidebar'
import { ThemeToggle } from './ThemeToggle'
import { UserMenu } from './UserMenu'

const KEY = 'talentlens.sidebar'
function readCollapsed(): boolean {
  try {
    return localStorage.getItem(KEY) === 'collapsed'
  } catch {
    return false
  }
}

/**
 * Authenticated layout: collapsible sidebar (desktop), sheet navigation (mobile), sticky header with search,
 * notifications and the user menu. Pages render into <Outlet/> inside <main id="main-content">.
 */
export function AppShell() {
  const [collapsed, setCollapsed] = useState(readCollapsed)
  const [mobileOpen, setMobileOpen] = useState(false)
  useFocusMainOnNavigate()

  const toggle = () =>
    setCollapsed((c) => {
      try {
        localStorage.setItem(KEY, c ? 'expanded' : 'collapsed')
      } catch {
        /* storage unavailable */
      }
      return !c
    })

  return (
    <div className="min-h-dvh bg-background">
      <SkipLink />
      <aside
        className={cn(
          'fixed inset-y-0 left-0 z-30 hidden border-r border-sidebar-border transition-[width] duration-200 lg:block',
          collapsed ? 'w-[68px]' : 'w-64',
        )}
      >
        <Sidebar collapsed={collapsed} onToggle={toggle} />
      </aside>

      <div className={cn('flex min-h-dvh min-w-0 flex-col transition-[padding] duration-200', collapsed ? 'lg:pl-[68px]' : 'lg:pl-64')}>
        <header className="sticky top-0 z-20 flex h-16 shrink-0 items-center gap-2 border-b bg-background/85 px-3 backdrop-blur-md sm:gap-3 sm:px-6">
          <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
            <SheetTrigger asChild>
              <Button variant="ghost" size="icon" className="lg:hidden" aria-label="Open navigation menu">
                <Menu />
              </Button>
            </SheetTrigger>
            <SheetContent side="left" className="gap-0 p-0" aria-describedby={undefined}>
              <SheetTitle className="sr-only">Navigation</SheetTitle>
              <SheetDescription className="sr-only">Main navigation</SheetDescription>
              <Sidebar onNavigate={() => setMobileOpen(false)} />
            </SheetContent>
          </Sheet>

          <GlobalSearch />
          <div className="ml-auto flex items-center gap-0.5 sm:gap-1">
            <ThemeToggle />
            <NotificationBell />
            <div className="ml-1">
              <UserMenu />
            </div>
          </div>
        </header>

        <main id="main-content" tabIndex={-1} className="flex-1 px-4 py-6 outline-none sm:px-6 lg:px-8 lg:py-8">
          <div className="mx-auto w-full max-w-7xl">
            <LayoutKindContext.Provider value="app">
              <Outlet />
            </LayoutKindContext.Provider>
          </div>
        </main>
      </div>
    </div>
  )
}
