import { useEffect } from 'react'

/** Sets `document.title` to "<title> · TalentLens" while the component is mounted. */
export function useDocumentTitle(title: string | null | undefined) {
  useEffect(() => {
    if (!title) return
    const previous = document.title
    document.title = `${title} · TalentLens`
    return () => {
      document.title = previous
    }
  }, [title])
}
