import { QueryClientProvider } from '@tanstack/react-query'
import { useState } from 'react'
import { RouterProvider } from 'react-router-dom'
import { Toaster } from 'sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
import { AuthProvider } from '@/features/auth/components/AuthProvider'
import { createQueryClient } from '@/lib/queryClient'
import { createAppRouter } from '@/routes'
import { useTheme } from '@/lib/theme'

function ThemedToaster() {
  const { theme } = useTheme()
  // sonner renders an aria-live region, so toasts are announced to screen readers.
  return (
    <Toaster
      theme={theme}
      position="top-right"
      closeButton
      richColors
      toastOptions={{ classNames: { toast: 'font-sans' } }}
    />
  )
}

export function App() {
  const [queryClient] = useState(createQueryClient)
  const [router] = useState(createAppRouter)
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <TooltipProvider delayDuration={250}>
          <RouterProvider router={router} />
          <ThemedToaster />
        </TooltipProvider>
      </AuthProvider>
    </QueryClientProvider>
  )
}
