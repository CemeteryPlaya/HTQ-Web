import React, { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { format, startOfMonth, endOfMonth, addMonths, subMonths } from 'date-fns';
import { TasksLayout } from '@/components/tasks/TasksLayout';
import { ResourceGantt } from '@/components/tasks/ResourceGantt';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { AlertCircle, Search, Users, Truck } from 'lucide-react';
import { fetchResourceGantt } from '@/api/tasks';
import type { ResourceKind } from '@/types/tasks';

type KindFilter = 'all' | ResourceKind;

const fmt = (d: Date) => format(d, 'yyyy-MM-dd');

const HRResourceSchedule: React.FC = () => {
  const navigate = useNavigate();
  const today = new Date();
  const [from, setFrom] = useState(fmt(startOfMonth(subMonths(today, 2))));
  const [to, setTo] = useState(fmt(endOfMonth(addMonths(today, 1))));
  const [kind, setKind] = useState<KindFilter>('all');
  const [search, setSearch] = useState('');

  const kinds = kind === 'all' ? 'employee,equipment' : kind;

  const { data, isLoading, error } = useQuery({
    queryKey: ['resource-gantt', from, to, kinds],
    queryFn: () => fetchResourceGantt({ from, to, kinds }),
  });

  const resources = useMemo(() => {
    const all = data?.resources ?? [];
    if (!search.trim()) return all;
    const q = search.toLowerCase();
    return all.filter((r) => r.resource_name.toLowerCase().includes(q));
  }, [data, search]);

  const stats = useMemo(() => {
    const emp = resources.filter((r) => r.resource_kind === 'employee').length;
    const eq = resources.filter((r) => r.resource_kind === 'equipment').length;
    const tasks = resources.reduce((n, r) => n + r.allocated_tasks.length, 0);
    return { emp, eq, tasks };
  }, [resources]);

  const KIND_TABS: { value: KindFilter; label: string }[] = [
    { value: 'all', label: 'Все' },
    { value: 'employee', label: 'Сотрудники' },
    { value: 'equipment', label: 'Техника' },
  ];

  return (
    <TasksLayout title="График работ" subtitle="Загрузка сотрудников и техники">
      {/* Панель управления */}
      <Card>
        <CardContent className="p-4">
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1 text-xs text-muted-foreground">
              Период с
              <Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className="h-9 w-[160px]" />
            </label>
            <label className="flex flex-col gap-1 text-xs text-muted-foreground">
              по
              <Input type="date" value={to} onChange={(e) => setTo(e.target.value)} className="h-9 w-[160px]" />
            </label>

            <div className="flex bg-muted/50 p-1 rounded-md border gap-1">
              {KIND_TABS.map((tab) => (
                <Button
                  key={tab.value}
                  variant={kind === tab.value ? 'secondary' : 'ghost'}
                  size="sm"
                  className="h-7 text-xs"
                  onClick={() => setKind(tab.value)}
                >
                  {tab.label}
                </Button>
              ))}
            </div>

            <div className="relative flex-1 min-w-[180px]">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input placeholder="Поиск ресурса" value={search} onChange={(e) => setSearch(e.target.value)} className="pl-9 h-9" />
            </div>
          </div>

          {/* Сводка */}
          <div className="mt-3 flex flex-wrap gap-4 text-sm text-muted-foreground">
            <span className="inline-flex items-center gap-1.5"><Users className="h-4 w-4" /> Сотрудники: <b className="text-foreground">{stats.emp}</b></span>
            <span className="inline-flex items-center gap-1.5"><Truck className="h-4 w-4" /> Техника: <b className="text-foreground">{stats.eq}</b></span>
            <span>Назначений задач: <b className="text-foreground">{stats.tasks}</b></span>
          </div>
        </CardContent>
      </Card>

      {/* Диаграмма */}
      <Card className="min-w-0">
        <CardHeader>
          <CardTitle>Диаграмма загрузки ресурсов</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="text-center py-12 text-muted-foreground">Загрузка данных...</div>
          ) : error ? (
            <div className="flex items-center gap-2 text-red-500 py-12 justify-center">
              <AlertCircle className="h-5 w-5" /> Ошибка загрузки данных
            </div>
          ) : (
            <ResourceGantt
              resources={resources}
              rangeFrom={from}
              rangeTo={to}
              onTaskClick={(taskId) => navigate(`/tasks/${taskId}`)}
            />
          )}
        </CardContent>
      </Card>
    </TasksLayout>
  );
};

export default HRResourceSchedule;
