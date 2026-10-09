import { useState } from 'react'

/**
 * Radix returns focus to the element that opened an overlay only when the overlay has a registered *Trigger*.
 * Our dialogs are usually controlled (opened from a menu item, a row action, a button elsewhere), so without this the
 * focus would be dropped on <body> when they close. We remember what had focus when the content mounted and give it back.
 *
 * Menu -> dialog: the menu item that opened the dialog disappears with its menu, so the DropdownMenu hands over its trigger
 * through `setFocusFallback` and the dialog restores focus there instead.
 */
let fallback: HTMLElement | null = null
export function setFocusFallback(el: HTMLElement | null) {
  fallback = el
}

export function useRestoreFocus(userHandler?: (event: Event) => void) {
  const [opener] = useState<Element | null>(() =>
    typeof document === 'undefined' ? null : document.activeElement,
  )
  return (event: Event) => {
    userHandler?.(event)
    if (event.defaultPrevented) return
    const usable = opener instanceof HTMLElement && opener.isConnected && opener !== document.body
    const target = usable ? opener : fallback?.isConnected ? fallback : null
    fallback = null
    if (target) {
      event.preventDefault()
      target.focus()
    }
  }
}
