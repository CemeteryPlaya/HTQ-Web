import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { TasksLayout } from '@/components/tasks/TasksLayout';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Textarea } from '@/components/ui/textarea';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from '@/components/ui/dialog';
import { toast } from 'sonner';
import { AlertCircle, Edit, Layers, MapPin, Plus, Search, Trash2 } from 'lucide-react';
import { createSite, deleteSite, fetchSites, updateSite } from '@/api/tasks';
import { SiteBlocksDialog } from '@/components/tasks/SiteBlocksDialog';
import type { Site, SiteStatus } from '@/types/tasks';

const SITE_STATUSES: SiteStatus[] = ['active', 'suspended', 'closed'];

const STATUS_BADGE: Record<SiteStatus, string> = {
  active: 'bg-green-500 text-white',
  suspended: 'bg-amber-500 text-white',
  closed: 'bg-gray-500 text-white',
};

const empty = {
  name: '', code: '', region: '', address: '',
  description: '', color: '#0ea5e9', status: 'active' as SiteStatus,
};

const HRSites: React.FC = () => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<Site | null>(null);
  const [form, setForm] = useState(empty);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  // Блоки правятся отдельным диалогом: у них своя форма с объёмами, и
  // вкладывать её в форму объекта значило бы городить диалог в диалоге.
  const [blocksSite, setBlocksSite] = useState<Site | null>(null);

  const { data: sites = [], isLoading, error } = useQuery({
    queryKey: ['sites', { search, statusFilter }],
    queryFn: () => fetchSites({
      search: search || undefined,
      status: statusFilter === 'all' ? undefined : statusFilter,
    }),
  });

  // Объект — сквозная ось: он виден в списке задач, в графике работ и в
  // отчётах, поэтому переименование или закрытие сбрасывает их все.
  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['sites'] });
    queryClient.invalidateQueries({ queryKey: ['hr-tasks'] });
    queryClient.invalidateQueries({ queryKey: ['hr-projects'] });
    queryClient.invalidateQueries({ queryKey: ['resource-gantt'] });
    queryClient.invalidateQueries({ queryKey: ['hr-task-stats'] });
  };

  const saveMutation = useMutation({
    mutationFn: (payload: typeof form) => {
      const body: Partial<Site> = {
        name: payload.name.trim(),
        code: payload.code.trim() || null,
        region: payload.region.trim() || null,
        address: payload.address.trim() || null,
        description: payload.description,
        color: payload.color,
        status: payload.status,
      };
      return editing ? updateSite(editing.id, body) : createSite(body);
    },
    onSuccess: () => {
      invalidate();
      setDialogOpen(false);
      toast.success(editing
        ? t('tasks.pages.sites.updated', 'Объект обновлён')
        : t('tasks.pages.sites.created', 'Объект добавлен'));
    },
    onError: () => toast.error(t('tasks.pages.sites.saveError', 'Не удалось сохранить')),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteSite(id),
    onSuccess: () => {
      invalidate();
      toast.success(t('tasks.pages.sites.deleted', 'Объект удалён'));
    },
    onError: (err: unknown) => {
      // 409 приходит с текстом, в котором названы счётчики задач и
      // проектов — показываем его, а не общую отписку: пользователю нужно
      // знать, что именно отвязать.
      const detail = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail;
      toast.error(detail
        || t('tasks.pages.sites.deleteError', 'Не удалось удалить объект'));
    },
  });

  const openCreate = () => { setEditing(null); setForm(empty); setDialogOpen(true); };
  const openEdit = (site: Site) => {
    setEditing(site);
    setForm({
      name: site.name,
      code: site.code ?? '',
      region: site.region ?? '',
      address: site.address ?? '',
      description: site.description ?? '',
      color: site.color,
      status: site.status,
    });
    setDialogOpen(true);
  };

  const statusLabel = (status: SiteStatus) =>
    t(`tasks.pages.sites.status.${status}`, status);

  return (
    <TasksLayout
      title={t('tasks.pages.sites.title', 'Объекты')}
      subtitle={t('tasks.pages.sites.subtitle', 'Площадки, на которых идут работы')}
    >
      <Card>
        <CardContent className="p-4 flex flex-wrap items-center gap-3">
          <div className="relative flex-1 min-w-[200px]">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder={t('tasks.pages.sites.search', 'Поиск объекта')}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-10"
            />
          </div>
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="w-[180px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">
                {t('tasks.pages.sites.allStatuses', 'Все статусы')}
              </SelectItem>
              {SITE_STATUSES.map((s) => (
                <SelectItem key={s} value={s}>{statusLabel(s)}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button onClick={openCreate} size="sm">
            <Plus className="h-4 w-4 mr-1" /> {t('common.add', 'Добавить')}
          </Button>
        </CardContent>
      </Card>

      <Card className="mt-4">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <MapPin className="h-5 w-5" />
            {t('tasks.pages.sites.title', 'Объекты')} ({sites.length})
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="text-center py-8 text-muted-foreground">
              {t('common.loading', 'Загрузка...')}
            </div>
          ) : error ? (
            <div className="flex items-center gap-2 text-red-500 py-8 justify-center">
              <AlertCircle className="h-5 w-5" />
              {t('tasks.pages.sites.loadError', 'Ошибка загрузки')}
            </div>
          ) : sites.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              {t('tasks.pages.sites.empty',
                'Объектов пока нет. Добавьте первый — например, «Алга».')}
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('tasks.pages.sites.name', 'Название')}</TableHead>
                  <TableHead className="w-[120px]">
                    {t('tasks.pages.sites.code', 'Код')}
                  </TableHead>
                  <TableHead className="w-[180px]">
                    {t('tasks.pages.sites.region', 'Регион')}
                  </TableHead>
                  <TableHead className="w-[130px]">
                    {t('tasks.pages.list.table.status')}
                  </TableHead>
                  <TableHead className="w-[110px] text-right">
                    {t('common.actions', 'Действия')}
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sites.map((site) => (
                  <TableRow key={site.id}>
                    <TableCell className="font-medium">
                      <span className="inline-flex items-center gap-2">
                        <span
                          className="inline-block h-3 w-3 rounded-full shrink-0"
                          style={{ backgroundColor: site.color }}
                        />
                        <Link
                          to={`/tasks?site_id=${site.id}`}
                          className="hover:underline"
                          title={t('tasks.pages.sites.openTasks',
                            'Показать задачи объекта')}
                        >
                          {site.name}
                        </Link>
                      </span>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {site.code || '—'}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {site.region || '—'}
                    </TableCell>
                    <TableCell>
                      <Badge className={STATUS_BADGE[site.status]}>
                        {statusLabel(site.status)}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-1">
                        <Button
                          size="icon" variant="ghost" className="h-7 w-7"
                          onClick={() => setBlocksSite(site)}
                          title={t('tasks.pages.blocks.title', 'Блоки объекта')}
                        >
                          <Layers className="h-4 w-4" />
                        </Button>
                        <Button
                          size="icon" variant="ghost" className="h-7 w-7"
                          onClick={() => openEdit(site)}
                          title={t('common.edit', 'Редактировать')}
                        >
                          <Edit className="h-4 w-4" />
                        </Button>
                        <Button
                          size="icon" variant="ghost"
                          className="h-7 w-7 text-muted-foreground hover:text-destructive"
                          title={t('common.delete', 'Удалить')}
                          onClick={() => {
                            if (window.confirm(t('tasks.pages.sites.deleteConfirm',
                              'Удалить объект «{{name}}»?', { name: site.name }))) {
                              deleteMutation.mutate(site.id);
                            }
                          }}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>
              {editing
                ? t('tasks.pages.sites.editTitle', 'Редактировать объект')
                : t('tasks.pages.sites.newTitle', 'Новый объект')}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label>{t('tasks.pages.sites.name', 'Название')} *</Label>
              <Input
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder={t('tasks.pages.sites.namePlaceholder', 'Алга')}
                className="mt-1"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>{t('tasks.pages.sites.code', 'Код')}</Label>
                <Input
                  value={form.code}
                  onChange={(e) => setForm({ ...form, code: e.target.value })}
                  placeholder="ALG"
                  className="mt-1"
                />
              </div>
              <div>
                <Label>{t('tasks.pages.sites.region', 'Регион')}</Label>
                <Input
                  value={form.region}
                  onChange={(e) => setForm({ ...form, region: e.target.value })}
                  placeholder={t('tasks.pages.sites.regionPlaceholder',
                    'Актюбинская область')}
                  className="mt-1"
                />
              </div>
            </div>
            <div>
              <Label>{t('tasks.pages.sites.address', 'Адрес')}</Label>
              <Input
                value={form.address}
                onChange={(e) => setForm({ ...form, address: e.target.value })}
                className="mt-1"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>{t('tasks.pages.list.table.status')}</Label>
                <Select
                  value={form.status}
                  onValueChange={(v) => setForm({ ...form, status: v as SiteStatus })}
                >
                  <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {SITE_STATUSES.map((s) => (
                      <SelectItem key={s} value={s}>{statusLabel(s)}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label>{t('tasks.projects.color', 'Цвет')}</Label>
                <Input
                  type="color"
                  value={form.color}
                  onChange={(e) => setForm({ ...form, color: e.target.value })}
                  className="mt-1"
                />
              </div>
            </div>
            <div>
              <Label>{t('tasks.projects.description', 'Описание')}</Label>
              <Textarea
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
                rows={3}
                className="mt-1"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>
              {t('common.cancel', 'Отмена')}
            </Button>
            <Button
              onClick={() => saveMutation.mutate(form)}
              disabled={!form.name.trim() || saveMutation.isPending}
            >
              {editing ? t('common.save', 'Сохранить') : t('common.add', 'Добавить')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <SiteBlocksDialog
        site={blocksSite}
        open={blocksSite !== null}
        onOpenChange={(open) => { if (!open) setBlocksSite(null); }}
      />
    </TasksLayout>
  );
};

export default HRSites;
