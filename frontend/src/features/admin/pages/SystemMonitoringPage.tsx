import { useQueryClient } from '@tanstack/react-query'
import { RefreshCw } from 'lucide-react'
import { PageHeader } from '@/components/common/PageHeader'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { useUrlState } from '@/hooks/useUrlState'
import { dates } from '@/lib/format'
import { adminKeys, useSystemStatus } from '../api/admin'
import type { TaskStatus, TaskType } from '../api/types'
import { AuditPanel } from '../components/AuditPanel'
import { HealthPanel } from '../components/HealthPanel'
import { ModelsPanel } from '../components/ModelsPanel'
import { TasksPanel } from '../components/TasksPanel'
import { useAutoRefresh } from '../hooks/useAutoRefresh'

const PAGE_SIZE = 20
const TABS = ['health', 'tasks', 'models', 'audit'] as const
type Tab = (typeof TABS)[number]

export default function SystemMonitoringPage() {
  useDocumentTitle('System monitoring')
  const qc = useQueryClient()
  const auto = useAutoRefresh()
  const polling = { refetchMs: auto.refetchMs }
  const [url, update] = useUrlState({
    tab: 'health',
    tstatus: '',
    ttype: '',
    tpage: 1,
    action: '',
    entity: '',
    from: '',
    to: '',
    apage: 1,
  })
  const tab: Tab = (TABS as readonly string[]).includes(url.tab) ? (url.tab as Tab) : 'health'
  const system = useSystemStatus(polling)

  return (
    <>
      <PageHeader
        title="System monitoring"
        description="Dependency health, background tasks, search models and the audit trail."
        actions={
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-2">
              <Switch
                id="auto-refresh"
                checked={auto.enabled}
                onCheckedChange={auto.setEnabled}
                aria-describedby="auto-refresh-hint"
              />
              <Label htmlFor="auto-refresh" className="cursor-pointer">
                Auto-refresh
              </Label>
              <span id="auto-refresh-hint" className="sr-only">
                Reloads every {auto.intervalMs / 1000} seconds while this tab is visible
              </span>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => void qc.invalidateQueries({ queryKey: adminKeys.all })}
              loading={system.isFetching && !system.isPending}
            >
              <RefreshCw /> Refresh now
            </Button>
          </div>
        }
        meta={
          system.dataUpdatedAt > 0 && (
            <span className="text-xs text-muted-foreground" role="status">
              Updated {dates.relative(new Date(system.dataUpdatedAt))}
              {auto.enabled && ` · refreshing every ${auto.intervalMs / 1000} s`}
            </span>
          )
        }
      />
      <Tabs value={tab} onValueChange={(t) => update({ tab: t === 'health' ? '' : t }, { resetPage: false })}>
        <TabsList aria-label="Monitoring sections" className="mb-4 max-w-full overflow-x-auto">
          <TabsTrigger value="health">Health</TabsTrigger>
          <TabsTrigger value="tasks">
            Background tasks
            {system.data && system.data.tasks.stale_count + (system.data.tasks.by_status.FAILED ?? 0) > 0 && (
              <span className="ml-1.5 inline-flex min-w-5 items-center justify-center rounded-full bg-destructive px-1.5 text-[11px] font-semibold text-white">
                {system.data.tasks.stale_count + (system.data.tasks.by_status.FAILED ?? 0)}
                <span className="sr-only"> need attention</span>
              </span>
            )}
          </TabsTrigger>
          <TabsTrigger value="models">Models and matching</TabsTrigger>
          <TabsTrigger value="audit">Audit log</TabsTrigger>
        </TabsList>
        <TabsContent value="health">
          <HealthPanel
            data={system.data}
            isPending={system.isPending}
            error={system.error}
            onRetry={() => system.refetch()}
          />
        </TabsContent>
        <TabsContent value="tasks">
          <TasksPanel
            health={system.data?.tasks}
            healthError={system.error}
            filters={{
              status: url.tstatus as TaskStatus | '',
              type: url.ttype as TaskType | '',
              page: url.tpage,
              pageSize: PAGE_SIZE,
            }}
            onFilters={(p) =>
              update(
                {
                  ...(p.tstatus !== undefined && { tstatus: p.tstatus }),
                  ...(p.ttype !== undefined && { ttype: p.ttype }),
                  tpage: p.tpage ?? 1,
                },
                { resetPage: false },
              )
            }
            polling={polling}
          />
        </TabsContent>
        <TabsContent value="models">
          <ModelsPanel polling={polling} />
        </TabsContent>
        <TabsContent value="audit">
          <AuditPanel
            filters={{
              action: url.action,
              entityType: url.entity,
              from: url.from,
              to: url.to,
              page: url.apage,
              pageSize: PAGE_SIZE,
            }}
            onFilters={(p) => update({ ...p, apage: p.apage ?? 1 }, { resetPage: false })}
            polling={polling}
          />
        </TabsContent>
      </Tabs>
    </>
  )
}
