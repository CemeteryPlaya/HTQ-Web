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

const STATUS_COLORS: Record<string, string> = {
  draft: '#cbd5e1', pending: '#f59e0b', approved: '#10b981',
  rejected: '#f43f5e', cancelled: '#64748b', returned: '#3b82f6',
};

function OverviewTab() {
  const overview = useQuery({
    queryKey: ['requests', 'stats', 'overview'],
    queryFn: () => requestsApi.stats.overview(),
  });
  const heatmap = useQuery({
    queryKey: ['requests', 'stats', 'heatmap'],
    queryFn: () => requestsApi.stats.heatmap(),
  });

  if (overview.isLoading) return <Skeleton className="h-48" />;
  if (!overview.data) return <p className="text-sm text-destructive">Не удалось загрузить.</p>;

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
                  сумма {v.sum_amount.toLocaleString('ru-RU')}
                </div>
              )}
            </CardContent>
          </Card>
        ))}
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader><CardTitle className="text-sm">Распределение по статусам</CardTitle></CardHeader>
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
          <CardHeader><CardTitle className="text-sm">Heatmap по дням</CardTitle></CardHeader>
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
          <SelectValue placeholder="— выберите проект —" />
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
            ['Сумма approved', stats.data.sum_approved?.toLocaleString('ru-RU')],
            ['Бюджет', stats.data.project?.budget_limit?.toLocaleString('ru-RU') ?? '—'],
            ['Остаток', stats.data.remaining?.toLocaleString('ru-RU') ?? '—'],
            ['% освоено', stats.data.percent_used != null ? `${stats.data.percent_used.toFixed(1)}%` : '—'],
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
          <TabsTrigger value="initiator">Инициаторы</TabsTrigger>
          <TabsTrigger value="approver">Согласующие</TabsTrigger>
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
              <Bar dataKey="count" fill="#3b82f6" name={role === 'initiator' ? 'подано' : 'обработано'} />
              <Bar dataKey="approved" fill={STATUS_COLORS.approved} />
            </BarChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>
    </div>
  );
}

export default function StatsPage() {
  return (
    <RequestsLayout title="Статистика запросов" subtitle="Финансовая и операционная отчётность">
      <Tabs defaultValue="overview" className="space-y-4">
        <TabsList>
          <TabsTrigger value="overview">Обзор</TabsTrigger>
          <TabsTrigger value="project">По проекту</TabsTrigger>
          <TabsTrigger value="template">По типам</TabsTrigger>
          <TabsTrigger value="actor">По людям</TabsTrigger>
        </TabsList>
        <TabsContent value="overview"><OverviewTab /></TabsContent>
        <TabsContent value="project"><ProjectTab /></TabsContent>
        <TabsContent value="template"><TemplateTab /></TabsContent>
        <TabsContent value="actor"><ActorTab /></TabsContent>
      </Tabs>
    </RequestsLayout>
  );
}
