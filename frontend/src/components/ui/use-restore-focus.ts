import { useState } from 'react'

/**
 * Radix returns focus to the element that opened an overlay only when the overlay has a registered *Trigger*.
 * Our dialogs are usually controlled (opened from a menu item, a row action, a button elsewhere), so without this the
 * focus would be dropped on <body> when they close. We remember what had focus when the content mounted and give it back.
 */
export function useRestoreFocus(userHandler?: (event: Event) => void) {
  const [opener] = useState<Element | null>(() =>
    typeof document === 'undefined' ? null : document.activeElement,
  )
  return (event: Event) => {
    userHandler?.(event)
    if (event.defaultPrevented) return
    if (opener instanceof HTMLElement && opener.isConnected && opener !== document.body) {
      event.preventDefault()
      opener.focus()
    }
  }
}
