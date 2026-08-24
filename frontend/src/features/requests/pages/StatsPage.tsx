/** /requests/stats — admin dashboards via recharts. */

import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Pie, PieChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

import { requestsApi } from '@/api/requests';
import { RequestsLayout } from '@/features/requests/RequestsLayout';
import { useProjects } from '@/features/requests/hooks';
import { useTranslation } from 'react-i18next';

const STATUS_COLORS: Record<string, string> = {
  draft: '#cbd5e1', pending: '#f59e0b', approved: '#10b981',
  rejected: '#f43f5e', cancelled: '#64748b', returned: '#3b82f6',
};

function OverviewTab() {
  const { t, i18n } = useTranslation();
  const overview = useQuery({
    queryKey: ['requests', 'stats', 'overview'],
    queryFn: () => requestsApi.stats.overview(),
  });
  const heatmap = useQuery({
    queryKey: ['requests', 'stats', 'heatmap'],
    queryFn: () => requestsApi.stats.heatmap(),
  });

  if (overview.isLoading) return <Skeleton className="h-48" />;
  if (!overview.data) return <p className="text-sm text-destructive">{t('requests.stats.loadError')}</p>;

  const byStatus = overview.data.by_status;
  const pieData = Object.entries(byStatus)
    .filter(([, v]) => v.count > 0)
    .map(([status, v]) => ({ name: status, value: v.count }));

  const heatData = (heatmap.data ?? []).map((r: any) => ({
    date: r.date.slice(5),
    approved: r.approved,
    rejected: r.rejected,
    cancelled: r.cancelled,
    created: r.created,
  }));

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {(Object.entries(byStatus) as Array<[string, { count: number; sum_amount: number }]>).map(([status, v]) => (
          <Card key={status}>
            <CardContent className="py-4">
              <div className="text-xs uppercase text-muted-foreground">{status}</div>
              <div className="mt-1 text-2xl font-semibold">{v.count}</div>
              {v.sum_amount > 0 && (
                <div className="text-xs text-muted-foreground">
                  {t('requests.stats.sumValue', { value: v.sum_amount.toLocaleString(i18n.language) })}
                </div>
              )}
            </CardContent>
          </Card>
        ))}
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader><CardTitle className="text-sm">{t('requests.stats.byStatus')}</CardTitle></CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={260}>
              <PieChart>
                <Pie data={pieData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={90} label>
                  {pieData.map((d) => <Cell key={d.name} fill={STATUS_COLORS[d.name] ?? '#94a3b8'} />)}
                </Pie>
                <Tooltip />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle className="text-sm">{t('requests.stats.heatmap')}</CardTitle></CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={heatData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" />
                <YAxis />
                <Tooltip />
                <Legend />
                <Bar dataKey="approved" stackId="a" fill={STATUS_COLORS.approved} />
                <Bar dataKey="rejected" stackId="a" fill={STATUS_COLORS.rejected} />
                <Bar dataKey="cancelled" stackId="a" fill={STATUS_COLORS.cancelled} />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function ProjectTab() {
  const { t, i18n } = useTranslation();
  const projects = useProjects();
  const [pid, setPid] = useState<string>('');
  const stats = useQuery({
    queryKey: ['requests', 'stats', 'by-project', pid],
    queryFn: () => requestsApi.stats.byProject(Number(pid)),
    enabled: pid !== '',
  });
  return (
    <div className="space-y-4">
      <Select value={pid} onValueChange={setPid}>
        <SelectTrigger className="w-72">
          <SelectValue placeholder={t('requests.stats.pickProject')} />
        </SelectTrigger>
        <SelectContent>
          {projects.data?.map((p) => (
            <SelectItem key={p.id} value={String(p.id)}>{p.name}</SelectItem>
          ))}
        </SelectContent>
      </Select>
      {stats.data && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {[
            [t('requests.stats.sumApproved'), stats.data.sum_approved?.toLocaleString(i18n.language)],
            [t('requests.stats.budget'), stats.data.project?.budget_limit?.toLocaleString(i18n.language) ?? '—'],
            [t('requests.stats.remaining'), stats.data.remaining?.toLocaleString(i18n.language) ?? '—'],
            [t('requests.stats.percentUsed'), stats.data.percent_used != null ? `${stats.data.percent_used.toFixed(1)}%` : '—'],
          ].map(([label, value]) => (
            <Card key={label as string}>
              <CardContent className="py-4">
                <div className="text-xs uppercase text-muted-foreground">{label}</div>
                <div className="mt-1 text-2xl font-semibold">{value}</div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

function TemplateTab() {
  const { t } = useTranslation();
  const rows = useQuery({
    queryKey: ['requests', 'stats', 'by-template'],
    queryFn: () => requestsApi.stats.byTemplate(),
  });
  const data = (rows.data ?? []) as Array<{ template_id: number; count: number; approved: number; rejected: number; avg_amount: number; approval_rate: number }>;
  return (
    <Card>
      <CardContent className="py-4">
        <ResponsiveContainer width="100%" height={Math.max(180, data.length * 36)}>
          <BarChart data={data} layout="vertical" margin={{ left: 20 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis type="number" />
            <YAxis type="category" dataKey="template_id" tickFormatter={(v) => `#${v}`} />
            <Tooltip />
            <Legend />
            <Bar dataKey="approved" fill={STATUS_COLORS.approved} />
            <Bar dataKey="rejected" fill={STATUS_COLORS.rejected} />
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}

function ActorTab() {
  const { t } = useTranslation();
  const [role, setRole] = useState<'initiator' | 'approver'>('initiator');
  const rows = useQuery({
    queryKey: ['requests', 'stats', 'by-actor', role],
    queryFn: () => requestsApi.stats.byActor({ role, limit: 20 }),
  });
  const data = (rows.data ?? []) as Array<{ user_id: number; count: number; approved: number; approval_rate: number }>;
  return (
    <div className="space-y-3">
      <Tabs value={role} onValueChange={(v) => setRole(v as 'initiator' | 'approver')}>
        <TabsList>
          <TabsTrigger value="initiator">{t('requests.stats.initiators')}</TabsTrigger>
          <TabsTrigger value="approver">{t('requests.stats.approvers')}</TabsTrigger>
        </TabsList>
      </Tabs>
      <Card>
        <CardContent className="py-4">
          <ResponsiveContainer width="100%" height={Math.max(180, data.length * 32)}>
            <BarChart data={data} layout="vertical" margin={{ left: 20 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis type="number" />
              <YAxis type="category" dataKey="user_id" tickFormatter={(v) => `#${v}`} width={60} />
              <Tooltip />
              <Legend />
              <Bar dataKey="count" fill="#3b82f6" name={role === 'initiator' ? t('requests.stats.submittedLower') : t('requests.stats.handledLower')} />
              <Bar dataKey="approved" fill={STATUS_COLORS.approved} />
            </BarChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>
    </div>
  );
}

export default function StatsPage() {
  const { t } = useTranslation();
  return (
    <RequestsLayout title={t('requests.stats.title')} subtitle={t('requests.stats.subtitle')}>
      <Tabs defaultValue="overview" className="space-y-4">
        <TabsList>
          <TabsTrigger value="overview">{t('requests.stats.tabOverview')}</TabsTrigger>
          <TabsTrigger value="project">{t('requests.stats.tabProject')}</TabsTrigger>
          <TabsTrigger value="template">{t('requests.stats.tabType')}</TabsTrigger>
          <TabsTrigger value="actor">{t('requests.stats.tabPeople')}</TabsTrigger>
        </TabsList>
        <TabsContent value="overview"><OverviewTab /></TabsContent>
        <TabsContent value="project"><ProjectTab /></TabsContent>
        <TabsContent value="template"><TemplateTab /></TabsContent>
        <TabsContent value="actor"><ActorTab /></TabsContent>
      </Tabs>
    </RequestsLayout>
  );
}
