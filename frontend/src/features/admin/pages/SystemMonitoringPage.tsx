import { UnderConstruction } from '@/components/common/UnderConstruction'

/** WAVE 2: replace this placeholder with the real page (keep the default export; the route already points here). */
export default function SystemMonitoringPage() {
  return (
    <UnderConstruction
      title="System monitoring"
      description="Health of the API, workers and queues."
      endpoints={['GET /health/ready', 'GET /admin/…']}
    />
  )
}
