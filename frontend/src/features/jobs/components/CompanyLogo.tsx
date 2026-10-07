import { Avatar } from '@/components/ui/avatar'

/** Company logo with initials fallback (squircle). */
export function CompanyLogo({
  name,
  logoUrl,
  size = 'md',
  className,
}: {
  name: string
  logoUrl?: string | null
  size?: 'sm' | 'md' | 'lg' | 'xl'
  className?: string
}) {
  return <Avatar name={name} src={logoUrl} size={size} shape="square" className={className} />
}
