import React, { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { format, startOfMonth, endOfMonth, addMonths, subMonths } from 'date-fns';
import { TasksLayout } from '@/components/tasks/TasksLayout';
import { ResourceGantt } from '@/components/tasks/ResourceGantt';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { AlertCircle, Search, Users, Truck } from 'lucide-react';
import { fetchProjects, fetchResourceGantt, fetchSites } from '@/api/tasks';
import type { ResourceKind } from '@/types/tasks';

type KindFilter = 'all' | ResourceKind;

const fmt = (d: Date) => format(d, 'yyyy-MM-dd');

const HRResourceSchedule: React.FC = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const today = new Date();
  const [from, setFrom] = useState(fmt(startOfMonth(subMonths(today, 2))));
  const [to, setTo] = useState(fmt(endOfMonth(addMonths(today, 1))));
  const [kind, setKind] = useState<KindFilter>('all');
  const [search, setSearch] = useState('');
  const [projectId, setProjectId] = useState<string>('all');
  const [siteId, setSiteId] = useState<string>('all');

  const kinds = kind === 'all' ? 'employee,equipment' : kind;

  const { data: projects = [] } = useQuery({
    queryKey: ['hr-projects'],
    queryFn: () => fetchProjects(),
  });
  const { data: sites = [] } = useQuery({
    queryKey: ['sites'],
    queryFn: () => fetchSites(),
  });

  // Проект и объект сужают выборку на сервере, до джойна назначений: иначе
  // строки ресурсов остались бы на месте с пустыми полосами, и график
  // выглядел бы загруженнее, чем он есть.
  const { data, isLoading, error } = useQuery({
    queryKey: ['resource-gantt', from, to, kinds, projectId, siteId],
    queryFn: () => fetchResourceGantt({
      from, to, kinds,
      project_id: projectId === 'all' ? undefined : Number(projectId),
      site_id: siteId === 'all' ? undefined : Number(siteId),
    }),
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
    { value: 'all', label: t('tasks.pages.resources.kindAll', 'Все') },
    { value: 'employee', label: t('tasks.pages.resources.kindEmployee', 'Сотрудники') },
    { value: 'equipment', label: t('tasks.pages.resources.kindEquipment', 'Техника') },
  ];

  return (
    <TasksLayout
      title={t('tasks.pages.resources.title', 'График работ')}
      subtitle={t('tasks.pages.resources.subtitle', 'Загрузка сотрудников и техники')}
    >
      {/* Панель управления */}
      <Card>
        <CardContent className="p-4">
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1 text-xs text-muted-foreground">
              {t('tasks.pages.resources.periodFrom', 'Период с')}
              <Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className="h-9 w-[160px]" />
            </label>
            <label className="flex flex-col gap-1 text-xs text-muted-foreground">
              {t('tasks.pages.resources.periodTo', 'по')}
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

            <Select value={projectId} onValueChange={setProjectId}>
              <SelectTrigger className="h-9 w-[180px]">
                <SelectValue placeholder={t('tasks.pages.list.table.project', 'Проект')} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">
                  {t('tasks.pages.list.allProjects', 'Все проекты')}
                </SelectItem>
                {projects.map((p) => (
                  <SelectItem key={p.id} value={String(p.id)}>{p.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Select value={siteId} onValueChange={setSiteId}>
              <SelectTrigger className="h-9 w-[180px]">
                <SelectValue placeholder={t('tasks.pages.sites.siteField', 'Объект')} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">
                  {t('tasks.pages.sites.allSites', 'Все объекты')}
                </SelectItem>
                {sites.map((s) => (
                  <SelectItem key={s.id} value={String(s.id)}>
                    <span className="inline-flex items-center gap-2">
                      <span className="inline-block h-2 w-2 rounded-full"
                        style={{ backgroundColor: s.color }} />
                      {s.name}
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <div className="relative flex-1 min-w-[180px]">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input placeholder={t('tasks.pages.resources.searchResource', 'Поиск ресурса')} value={search} onChange={(e) => setSearch(e.target.value)} className="pl-9 h-9" />
            </div>
          </div>

          {/* Сводка */}
          <div className="mt-3 flex flex-wrap gap-4 text-sm text-muted-foreground">
            <span className="inline-flex items-center gap-1.5"><Users className="h-4 w-4" /> {t('tasks.pages.resources.kindEmployee', 'Сотрудники')}: <b className="text-foreground">{stats.emp}</b></span>
            <span className="inline-flex items-center gap-1.5"><Truck className="h-4 w-4" /> {t('tasks.pages.resources.kindEquipment', 'Техника')}: <b className="text-foreground">{stats.eq}</b></span>
            <span>{t('tasks.pages.resources.assignmentsCount', 'Назначений задач')}: <b className="text-foreground">{stats.tasks}</b></span>
          </div>
        </CardContent>
      </Card>

      {/* Диаграмма */}
      <Card className="min-w-0">
        <CardHeader>
          <CardTitle>{t('tasks.pages.resources.chartTitle', 'Диаграмма загрузки ресурсов')}</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="text-center py-12 text-muted-foreground">{t('common.loading', 'Загрузка...')}</div>
          ) : error ? (
            <div className="flex items-center gap-2 text-red-500 py-12 justify-center">
              <AlertCircle className="h-5 w-5" /> {t('tasks.pages.resources.loadError', 'Ошибка загрузки данных')}
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
