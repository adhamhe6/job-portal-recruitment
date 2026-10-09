import { fmt } from '@/lib/format'

export const BULK_ACCEPT = ['.pdf', '.docx']
/** Mirrors backend settings (max_resume_mb, max_bulk_import_files). */
export const BULK_MAX_FILE_MB = 5
export const BULK_MAX_FILES = 200
/** The reverse proxy accepts ~12 MB per request (nginx.conf), so big selections are split into several uploads. */
export const BULK_REQUEST_MB = 10

export interface PickResult {
  accepted: File[]
  problems: { name: string; reason: string }[]
}

const keyOf = (f: File) => `${f.name}:${f.size}`

/** Client-side pre-checks (the server re-validates by content): type, size, empty, duplicates, count. */
export function pickFiles(existing: File[], incoming: File[]): PickResult {
  const seen = new Set(existing.map(keyOf))
  const accepted: File[] = []
  const problems: PickResult['problems'] = []
  for (const f of incoming) {
    const lower = f.name.toLowerCase()
    if (!BULK_ACCEPT.some((ext) => lower.endsWith(ext))) {
      problems.push({
        name: f.name,
        reason: lower.endsWith('.zip')
          ? 'ZIP archives are not supported. Extract it and add the PDF or DOCX files.'
          : 'Only PDF and DOCX files are supported.',
      })
    } else if (f.size === 0) problems.push({ name: f.name, reason: 'The file is empty.' })
    else if (f.size > BULK_MAX_FILE_MB * 1024 * 1024)
      problems.push({ name: f.name, reason: `Larger than ${BULK_MAX_FILE_MB} MB.` })
    else if (seen.has(keyOf(f))) problems.push({ name: f.name, reason: 'Already in the list.' })
    else if (existing.length + accepted.length >= BULK_MAX_FILES)
      problems.push({ name: f.name, reason: `At most ${BULK_MAX_FILES} files per import.` })
    else {
      seen.add(keyOf(f))
      accepted.push(f)
    }
  }
  return { accepted, problems }
}

/** Greedy split into request-sized groups (each <= BULK_REQUEST_MB and <= BULK_MAX_FILES files). */
export function chunkFiles(files: File[], maxBytes = BULK_REQUEST_MB * 1024 * 1024): File[][] {
  const chunks: File[][] = []
  let cur: File[] = []
  let size = 0
  for (const f of files) {
    if (cur.length > 0 && (size + f.size > maxBytes || cur.length >= BULK_MAX_FILES)) {
      chunks.push(cur)
      cur = []
      size = 0
    }
    cur.push(f)
    size += f.size
  }
  if (cur.length) chunks.push(cur)
  return chunks
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${fmt.int(Math.round(bytes / 1024))} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/** Plain-language reason for an item's backend error code. */
export const ITEM_REASONS: Record<string, string> = {
  DUPLICATE_FILE: 'Your company already imported this exact file.',
  DUPLICATE_CANDIDATE: 'A candidate with this e-mail address already exists.',
  NO_CANDIDATE_IDENTIFIED: 'No name or e-mail address could be found in the résumé.',
}
