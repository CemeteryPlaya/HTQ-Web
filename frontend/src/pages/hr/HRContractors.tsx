import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { TasksLayout } from '@/components/tasks/TasksLayout';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Textarea } from '@/components/ui/textarea';
import { PhoneInput } from '@/components/ui/phone-input';
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
import {
  AlertCircle, Edit, HardHat, MapPin, Plus, Search, Trash2, UserMinus, Users,
} from 'lucide-react';
import {
  createContractor, createContractorWorker, createEngagement,
  deactivateContractorWorker, deleteContractor, deleteEngagement,
  fetchContractors, fetchContractorWorkers, fetchEngagements,
  fetchProjects, fetchSites, updateContractor, updateContractorWorker,
} from '@/api/tasks';
import type {
  Contractor, ContractorLevel, ContractorStatus, ContractorWorker,
} from '@/types/tasks';

const STATUSES: ContractorStatus[] = ['active', 'suspended', 'blacklisted', 'archived'];
const LEVELS: ContractorLevel[] = ['junior', 'middle', 'senior'];

const STATUS_BADGE: Record<ContractorStatus, string> = {
  active: 'bg-green-500 text-white',
  suspended: 'bg-amber-500 text-white',
  blacklisted: 'bg-red-600 text-white',
  archived: 'bg-gray-500 text-white',
};

const LEVEL_BADGE: Record<ContractorLevel, string> = {
  junior: 'bg-slate-400 text-white',
  middle: 'bg-blue-600 text-white',
  senior: 'bg-purple-600 text-white',
};

const emptyContractor = {
  name: '', short_name: '', bin_iin: '', contact_person: '',
  phone: '', email: '', address: '', notes: '',
  status: 'active' as ContractorStatus,
};

const emptyWorker = {
  last_name: '', first_name: '', middle_name: '', phone: '', email: '',
  position_title: '', level: 'junior' as ContractorLevel,
};

const emptyEngagement = {
  project_id: '', site_id: '', contract_no: '', scope: '',
  start_date: '', end_date: '',
};

const HRContractors: React.FC = () => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const [contractorDialog, setContractorDialog] = useState(false);
  const [editingContractor, setEditingContractor] = useState<Contractor | null>(null);
  const [contractorForm, setContractorForm] = useState(emptyContractor);

  const [workerDialog, setWorkerDialog] = useState(false);
  const [editingWorker, setEditingWorker] = useState<ContractorWorker | null>(null);
  const [workerForm, setWorkerForm] = useState(emptyWorker);

  const [engagementDialog, setEngagementDialog] = useState(false);
  const [engagementForm, setEngagementForm] = useState(emptyEngagement);

  const { data: contractors = [], isLoading, error } = useQuery({
    queryKey: ['contractors', { search, statusFilter }],
    queryFn: () => fetchContractors({
      search: search || undefined,
      status: statusFilter === 'all' ? undefined : statusFilter,
    }),
  });

  const selected = contractors.find((c) => c.id === selectedId) ?? null;

  const { data: workers = [] } = useQuery({
    queryKey: ['contractor-workers', selectedId],
    queryFn: () => fetchContractorWorkers(selectedId!, false),
    enabled: selectedId !== null,
  });

  const { data: engagements = [] } = useQuery({
    queryKey: ['engagements', selectedId],
    queryFn: () => fetchEngagements({ contractor_id: selectedId! }),
    enabled: selectedId !== null,
  });

  const { data: projects = [] } = useQuery({
    queryKey: ['hr-projects'], queryFn: () => fetchProjects(),
  });
  const { data: sites = [] } = useQuery({
    queryKey: ['sites'], queryFn: () => fetchSites(),
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['contractors'] });
    queryClient.invalidateQueries({ queryKey: ['contractor-workers'] });
    queryClient.invalidateQueries({ queryKey: ['engagements'] });
    queryClient.invalidateQueries({ queryKey: ['hr-tasks'] });
    queryClient.invalidateQueries({ queryKey: ['equipment'] });
  };

  const fail = (fallbackKey: string, fallback: string) => (err: unknown) => {
    const detail = (err as { response?: { data?: { detail?: string } } })
      ?.response?.data?.detail;
    toast.error(typeof detail === 'string' ? detail : t(fallbackKey, fallback));
  };

  const contractorMutation = useMutation({
    mutationFn: (payload: typeof contractorForm) => {
      const body: Partial<Contractor> = {
        name: payload.name.trim(),
        short_name: payload.short_name.trim() || null,
        bin_iin: payload.bin_iin.trim() || null,
        contact_person: payload.contact_person.trim() || null,
        phone: payload.phone || null,
        email: payload.email.trim() || null,
        address: payload.address.trim() || null,
        notes: payload.notes,
        status: payload.status,
      };
      return editingContractor
        ? updateContractor(editingContractor.id, body)
        : createContractor(body);
    },
    onSuccess: () => {
      invalidate();
      setContractorDialog(false);
      toast.success(editingContractor
        ? t('tasks.pages.contractors.updated', 'Подрядчик обновлён')
        : t('tasks.pages.contractors.created', 'Подрядчик добавлен'));
    },
    onError: fail('tasks.pages.contractors.saveError', 'Не удалось сохранить'),
  });

  const deleteContractorMutation = useMutation({
    mutationFn: (id: number) => deleteContractor(id),
    onSuccess: () => {
      invalidate();
      setSelectedId(null);
      toast.success(t('tasks.pages.contractors.deleted', 'Подрядчик удалён'));
    },
    onError: fail('tasks.pages.contractors.deleteError', 'Не удалось удалить'),
  });

  const workerMutation = useMutation({
    mutationFn: (payload: typeof workerForm) => {
      const body: Partial<ContractorWorker> = {
        last_name: payload.last_name.trim(),
        first_name: payload.first_name.trim(),
        middle_name: payload.middle_name.trim() || null,
        phone: payload.phone || null,
        email: payload.email.trim() || null,
        position_title: payload.position_title.trim() || null,
        level: payload.level,
      };
      return editingWorker
        ? updateContractorWorker(editingWorker.id, body)
        : createContractorWorker(selectedId!, body);
    },
    onSuccess: () => {
      invalidate();
      setWorkerDialog(false);
      toast.success(t('tasks.pages.contractors.workerSaved', 'Сотрудник сохранён'));
    },
    onError: fail('tasks.pages.contractors.saveError', 'Не удалось сохранить'),
  });

  const deactivateWorkerMutation = useMutation({
    mutationFn: (id: number) => deactivateContractorWorker(id),
    onSuccess: () => {
      invalidate();
      toast.success(t('tasks.pages.contractors.workerDeactivated', 'Сотрудник отключён'));
    },
    onError: fail('tasks.pages.contractors.saveError', 'Не удалось сохранить'),
  });

  const restoreWorkerMutation = useMutation({
    mutationFn: (id: number) => updateContractorWorker(id, { is_active: true }),
    onSuccess: () => {
      invalidate();
      toast.success(t('tasks.pages.contractors.workerRestored', 'Сотрудник возвращён'));
    },
    onError: fail('tasks.pages.contractors.saveError', 'Не удалось сохранить'),
  });

  const engagementMutation = useMutation({
    mutationFn: (payload: typeof emptyEngagement) => createEngagement({
      contractor_id: selectedId!,
      project_id: payload.project_id ? Number(payload.project_id) : null,
      site_id: payload.site_id ? Number(payload.site_id) : null,
      contract_no: payload.contract_no.trim() || null,
      scope: payload.scope,
      start_date: payload.start_date || null,
      end_date: payload.end_date || null,
    }),
    onSuccess: () => {
      invalidate();
      setEngagementDialog(false);
      toast.success(t('tasks.pages.contractors.engagementCreated', 'Привлечение добавлено'));
    },
    onError: fail('tasks.pages.contractors.saveError', 'Не удалось сохранить'),
  });

  const deleteEngagementMutation = useMutation({
    mutationFn: (id: number) => deleteEngagement(id),
    onSuccess: invalidate,
    onError: fail('tasks.pages.contractors.deleteError', 'Не удалось удалить'),
  });

  const openCreateContractor = () => {
    setEditingContractor(null);
    setContractorForm(emptyContractor);
    setContractorDialog(true);
  };
  const openEditContractor = (c: Contractor) => {
    setEditingContractor(c);
    setContractorForm({
      name: c.name, short_name: c.short_name ?? '', bin_iin: c.bin_iin ?? '',
      contact_person: c.contact_person ?? '', phone: c.phone ?? '',
      email: c.email ?? '', address: c.address ?? '', notes: c.notes ?? '',
      status: c.status,
    });
    setContractorDialog(true);
  };
  const openCreateWorker = () => {
    setEditingWorker(null); setWorkerForm(emptyWorker); setWorkerDialog(true);
  };
  const openEditWorker = (w: ContractorWorker) => {
    setEditingWorker(w);
    setWorkerForm({
      last_name: w.last_name, first_name: w.first_name,
      middle_name: w.middle_name ?? '', phone: w.phone ?? '',
      email: w.email ?? '', position_title: w.position_title ?? '',
      level: w.level,
    });
    setWorkerDialog(true);
  };

  const statusLabel = (s: ContractorStatus) =>
    t(`tasks.pages.contractors.status.${s}`, s);
  const levelLabel = (l: ContractorLevel) =>
    t(`tasks.pages.contractors.level.${l}`, l);

  return (
    <TasksLayout
      title={t('tasks.pages.contractors.title', 'Субподрядчики')}
      subtitle={t('tasks.pages.contractors.subtitle',
        'Организации, их люди и привлечения на объекты')}
    >
      <div className="grid gap-4 lg:grid-cols-[minmax(0,380px)_minmax(0,1fr)] items-start">
        {/* ── Организации ── */}
        <Card className="lg:sticky lg:top-4">
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center justify-between gap-2 text-base">
              <span className="flex items-center gap-2">
                <HardHat className="h-5 w-5" />
                {t('tasks.pages.contractors.title', 'Субподрядчики')} ({contractors.length})
              </span>
              {/* Кнопка-иконка обязана нести доступное имя: без него её не
                  озвучит скринридер и не подскажет тултип при наведении. */}
              <Button
                size="sm"
                onClick={openCreateContractor}
                title={t('tasks.pages.contractors.newTitle', 'Новый подрядчик')}
                aria-label={t('tasks.pages.contractors.newTitle', 'Новый подрядчик')}
              >
                <Plus className="h-4 w-4" />
              </Button>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder={t('tasks.pages.contractors.search', 'Поиск подрядчика')}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pl-9 h-9"
              />
            </div>
            <Select value={statusFilter} onValueChange={setStatusFilter}>
              <SelectTrigger className="h-9"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">
                  {t('tasks.pages.contractors.allStatuses', 'Все статусы')}
                </SelectItem>
                {STATUSES.map((s) => (
                  <SelectItem key={s} value={s}>{statusLabel(s)}</SelectItem>
                ))}
              </SelectContent>
            </Select>

            {isLoading ? (
              <p className="text-sm text-muted-foreground py-6 text-center">
                {t('common.loading', 'Загрузка...')}
              </p>
            ) : error ? (
              <p className="flex items-center gap-2 text-red-500 py-6 justify-center text-sm">
                <AlertCircle className="h-4 w-4" />
                {t('tasks.pages.contractors.loadError', 'Ошибка загрузки')}
              </p>
            ) : contractors.length === 0 ? (
              <p className="text-sm text-muted-foreground py-6 text-center">
                {t('tasks.pages.contractors.empty', 'Подрядчиков пока нет')}
              </p>
            ) : (
              <div className="space-y-1">
                {contractors.map((c) => (
                  <button
                    key={c.id}
                    type="button"
                    onClick={() => setSelectedId(c.id)}
                    className={`w-full text-left rounded-md px-3 py-2 transition-colors ${
                      selectedId === c.id ? 'bg-muted' : 'hover:bg-muted/60'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium truncate">{c.name}</span>
                      <Badge className={`${STATUS_BADGE[c.status]} shrink-0`}>
                        {statusLabel(c.status)}
                      </Badge>
                    </div>
                    {c.contact_person && (
                      <div className="text-xs text-muted-foreground truncate">
                        {c.contact_person}{c.phone ? ` · ${c.phone}` : ''}
                      </div>
                    )}
                  </button>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* ── Детали ── */}
        {selected === null ? (
          <Card>
            <CardContent className="py-16 text-center text-muted-foreground">
              {t('tasks.pages.contractors.pickOne',
                'Выберите подрядчика слева, чтобы увидеть его людей и привлечения.')}
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-4 min-w-0">
            <Card>
              <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
                <div className="min-w-0">
                  <CardTitle>{selected.name}</CardTitle>
                  <div className="mt-1 text-sm text-muted-foreground space-y-0.5">
                    {selected.bin_iin && (
                      <div>{t('tasks.pages.contractors.bin', 'БИН/ИИН')}: {selected.bin_iin}</div>
                    )}
                    {selected.contact_person && <div>{selected.contact_person}</div>}
                    {selected.phone && <div>{selected.phone}</div>}
                    {selected.email && <div>{selected.email}</div>}
                    {selected.address && <div>{selected.address}</div>}
                  </div>
                </div>
                <div className="flex gap-1 shrink-0">
                  <Button size="icon" variant="ghost" className="h-8 w-8"
                    onClick={() => openEditContractor(selected)}
                    title={t('common.edit', 'Редактировать')}>
                    <Edit className="h-4 w-4" />
                  </Button>
                  <Button size="icon" variant="ghost"
                    className="h-8 w-8 text-muted-foreground hover:text-destructive"
                    title={t('common.delete', 'Удалить')}
                    onClick={() => {
                      if (window.confirm(t('tasks.pages.contractors.deleteConfirm',
                        'Удалить подрядчика «{{name}}»?', { name: selected.name }))) {
                        deleteContractorMutation.mutate(selected.id);
                      }
                    }}>
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </CardHeader>
            </Card>

            {/* Люди */}
            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0">
                <CardTitle className="flex items-center gap-2 text-base">
                  <Users className="h-4 w-4" />
                  {t('tasks.pages.contractors.workers', 'Сотрудники')} ({workers.length})
                </CardTitle>
                <Button size="sm" onClick={openCreateWorker}>
                  <Plus className="h-4 w-4 mr-1" /> {t('common.add', 'Добавить')}
                </Button>
              </CardHeader>
              <CardContent>
                <p className="mb-3 text-xs text-muted-foreground">
                  {t('tasks.pages.contractors.levelHint',
                    'Уровень определяет будущие права представителя. Пока подрядчики в систему не заходят — права заработают, когда включим вход.')}
                </p>
                {workers.length === 0 ? (
                  <p className="text-sm text-muted-foreground py-4 text-center">
                    {t('tasks.pages.contractors.noWorkers', 'Сотрудники не добавлены')}
                  </p>
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>{t('tasks.pages.contractors.fio', 'ФИО')}</TableHead>
                        <TableHead className="w-[180px]">
                          {t('tasks.pages.contractors.position', 'Должность')}
                        </TableHead>
                        <TableHead className="w-[120px]">
                          {t('tasks.pages.contractors.level.title', 'Уровень')}
                        </TableHead>
                        <TableHead className="w-[150px]">
                          {t('settingsPage.phone', 'Телефон')}
                        </TableHead>
                        <TableHead className="w-[90px] text-right">
                          {t('common.actions', 'Действия')}
                        </TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {workers.map((w) => (
                        <TableRow key={w.id} className={w.is_active ? undefined : 'opacity-60'}>
                          <TableCell className="font-medium">
                            {w.full_name}
                            {!w.is_active && (
                              <Badge variant="outline" className="ml-2 font-normal">
                                {t('tasks.pages.contractors.inactive', 'отключён')}
                              </Badge>
                            )}
                          </TableCell>
                          <TableCell className="text-sm text-muted-foreground">
                            {w.position_title || '—'}
                          </TableCell>
                          <TableCell>
                            <Badge className={LEVEL_BADGE[w.level]}>{levelLabel(w.level)}</Badge>
                          </TableCell>
                          <TableCell className="text-sm text-muted-foreground">
                            {w.phone || '—'}
                          </TableCell>
                          <TableCell>
                            <div className="flex justify-end gap-1">
                              <Button size="icon" variant="ghost" className="h-7 w-7"
                                onClick={() => openEditWorker(w)}
                                title={t('common.edit', 'Редактировать')}>
                                <Edit className="h-4 w-4" />
                              </Button>
                              {w.is_active ? (
                                <Button size="icon" variant="ghost"
                                  className="h-7 w-7 text-muted-foreground hover:text-destructive"
                                  title={t('tasks.pages.contractors.deactivate', 'Отключить')}
                                  onClick={() => deactivateWorkerMutation.mutate(w.id)}>
                                  <UserMinus className="h-4 w-4" />
                                </Button>
                              ) : (
                                <Button size="icon" variant="ghost"
                                  className="h-7 w-7 text-muted-foreground hover:text-primary"
                                  title={t('tasks.pages.contractors.restore', 'Вернуть')}
                                  onClick={() => restoreWorkerMutation.mutate(w.id)}>
                                  <Users className="h-4 w-4" />
                                </Button>
                              )}
                            </div>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </CardContent>
            </Card>

            {/* Привлечения */}
            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0">
                <CardTitle className="flex items-center gap-2 text-base">
                  <MapPin className="h-4 w-4" />
                  {t('tasks.pages.contractors.engagements', 'Привлечения')} ({engagements.length})
                </CardTitle>
                <Button size="sm" onClick={() => {
                  setEngagementForm(emptyEngagement); setEngagementDialog(true);
                }}>
                  <Plus className="h-4 w-4 mr-1" /> {t('common.add', 'Добавить')}
                </Button>
              </CardHeader>
              <CardContent>
                {engagements.length === 0 ? (
                  <p className="text-sm text-muted-foreground py-4 text-center">
                    {t('tasks.pages.contractors.noEngagements',
                      'Подрядчик ещё не привлечён ни на один объект')}
                  </p>
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>{t('tasks.pages.sites.siteField', 'Объект')}</TableHead>
                        <TableHead>{t('tasks.pages.list.table.project', 'Проект')}</TableHead>
                        <TableHead className="w-[130px]">
                          {t('tasks.pages.contractors.contractNo', 'Договор')}
                        </TableHead>
                        <TableHead className="w-[190px]">
                          {t('tasks.pages.contractors.period', 'Период')}
                        </TableHead>
                        <TableHead className="w-[60px] text-right"></TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {engagements.map((e) => (
                        <TableRow key={e.id} className={e.is_active ? undefined : 'opacity-60'}>
                          <TableCell>{e.site_name || '—'}</TableCell>
                          <TableCell className="text-sm text-muted-foreground">
                            {e.project_name || '—'}
                          </TableCell>
                          <TableCell className="text-sm text-muted-foreground">
                            {e.contract_no || '—'}
                          </TableCell>
                          <TableCell className="text-sm text-muted-foreground">
                            {e.start_date || '—'} — {e.end_date || '…'}
                          </TableCell>
                          <TableCell>
                            <div className="flex justify-end">
                              <Button size="icon" variant="ghost"
                                className="h-7 w-7 text-muted-foreground hover:text-destructive"
                                title={t('common.delete', 'Удалить')}
                                onClick={() => deleteEngagementMutation.mutate(e.id)}>
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
          </div>
        )}
      </div>

      {/* ── Диалог организации ── */}
      <Dialog open={contractorDialog} onOpenChange={setContractorDialog}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>
              {editingContractor
                ? t('tasks.pages.contractors.editTitle', 'Редактировать подрядчика')
                : t('tasks.pages.contractors.newTitle', 'Новый подрядчик')}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label>{t('tasks.pages.contractors.name', 'Наименование')} *</Label>
              <Input value={contractorForm.name} className="mt-1"
                placeholder={t('tasks.pages.contractors.namePlaceholder', 'ТОО «СтройМонтаж»')}
                onChange={(e) => setContractorForm({ ...contractorForm, name: e.target.value })} />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>{t('tasks.pages.contractors.shortName', 'Короткое имя')}</Label>
                <Input value={contractorForm.short_name} className="mt-1"
                  onChange={(e) => setContractorForm({ ...contractorForm, short_name: e.target.value })} />
              </div>
              <div>
                <Label>{t('tasks.pages.contractors.bin', 'БИН/ИИН')}</Label>
                <Input value={contractorForm.bin_iin} className="mt-1"
                  inputMode="numeric" maxLength={12} placeholder="123456789012"
                  onChange={(e) => setContractorForm({
                    ...contractorForm,
                    bin_iin: e.target.value.replace(/\D/g, '').slice(0, 12),
                  })} />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>{t('tasks.pages.contractors.contactPerson', 'Контактное лицо')}</Label>
                <Input value={contractorForm.contact_person} className="mt-1"
                  onChange={(e) => setContractorForm({ ...contractorForm, contact_person: e.target.value })} />
              </div>
              <div>
                <Label>{t('settingsPage.phone', 'Телефон')}</Label>
                <div className="mt-1">
                  <PhoneInput
                    value={contractorForm.phone}
                    onChange={(v) => setContractorForm({ ...contractorForm, phone: v })}
                  />
                </div>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>Email</Label>
                <Input value={contractorForm.email} className="mt-1" type="email"
                  onChange={(e) => setContractorForm({ ...contractorForm, email: e.target.value })} />
              </div>
              <div>
                <Label>{t('tasks.pages.list.table.status')}</Label>
                <Select value={contractorForm.status}
                  onValueChange={(v) => setContractorForm({ ...contractorForm, status: v as ContractorStatus })}>
                  <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {STATUSES.map((s) => (
                      <SelectItem key={s} value={s}>{statusLabel(s)}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div>
              <Label>{t('tasks.pages.sites.address', 'Адрес')}</Label>
              <Input value={contractorForm.address} className="mt-1"
                onChange={(e) => setContractorForm({ ...contractorForm, address: e.target.value })} />
            </div>
            <div>
              <Label>{t('tasks.pages.contractors.notes', 'Заметки')}</Label>
              <Textarea value={contractorForm.notes} rows={3} className="mt-1"
                onChange={(e) => setContractorForm({ ...contractorForm, notes: e.target.value })} />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setContractorDialog(false)}>
              {t('common.cancel', 'Отмена')}
            </Button>
            <Button onClick={() => contractorMutation.mutate(contractorForm)}
              disabled={!contractorForm.name.trim() || contractorMutation.isPending}>
              {editingContractor ? t('common.save', 'Сохранить') : t('common.add', 'Добавить')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Диалог сотрудника ── */}
      <Dialog open={workerDialog} onOpenChange={setWorkerDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {editingWorker
                ? t('tasks.pages.contractors.editWorker', 'Редактировать сотрудника')
                : t('tasks.pages.contractors.newWorker', 'Новый сотрудник')}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>{t('profile.lastName', 'Фамилия')} *</Label>
                <Input value={workerForm.last_name} className="mt-1"
                  onChange={(e) => setWorkerForm({ ...workerForm, last_name: e.target.value })} />
              </div>
              <div>
                <Label>{t('profile.firstName', 'Имя')} *</Label>
                <Input value={workerForm.first_name} className="mt-1"
                  onChange={(e) => setWorkerForm({ ...workerForm, first_name: e.target.value })} />
              </div>
            </div>
            <div>
              <Label>{t('profile.patronymic', 'Отчество')}</Label>
              <Input value={workerForm.middle_name} className="mt-1"
                onChange={(e) => setWorkerForm({ ...workerForm, middle_name: e.target.value })} />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>{t('tasks.pages.contractors.position', 'Должность')}</Label>
                <Input value={workerForm.position_title} className="mt-1"
                  placeholder={t('tasks.pages.contractors.positionPlaceholder', 'Прораб')}
                  onChange={(e) => setWorkerForm({ ...workerForm, position_title: e.target.value })} />
              </div>
              <div>
                <Label>{t('tasks.pages.contractors.level.title', 'Уровень')}</Label>
                <Select value={workerForm.level}
                  onValueChange={(v) => setWorkerForm({ ...workerForm, level: v as ContractorLevel })}>
                  <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {LEVELS.map((l) => (
                      <SelectItem key={l} value={l}>{levelLabel(l)}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <p className="text-xs text-muted-foreground">
              {t(`tasks.pages.contractors.levelDesc.${workerForm.level}`, '')}
            </p>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>{t('settingsPage.phone', 'Телефон')}</Label>
                <div className="mt-1">
                  <PhoneInput value={workerForm.phone}
                    onChange={(v) => setWorkerForm({ ...workerForm, phone: v })} />
                </div>
              </div>
              <div>
                <Label>Email</Label>
                <Input value={workerForm.email} className="mt-1" type="email"
                  onChange={(e) => setWorkerForm({ ...workerForm, email: e.target.value })} />
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setWorkerDialog(false)}>
              {t('common.cancel', 'Отмена')}
            </Button>
            <Button onClick={() => workerMutation.mutate(workerForm)}
              disabled={!workerForm.last_name.trim() || !workerForm.first_name.trim()
                || workerMutation.isPending}>
              {editingWorker ? t('common.save', 'Сохранить') : t('common.add', 'Добавить')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Диалог привлечения ── */}
      <Dialog open={engagementDialog} onOpenChange={setEngagementDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {t('tasks.pages.contractors.newEngagement', 'Новое привлечение')}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <p className="text-xs text-muted-foreground">
              {t('tasks.pages.contractors.engagementHint',
                'Укажите объект, проект или и то и другое — хотя бы одно обязательно.')}
            </p>
            <div>
              <Label>{t('tasks.pages.sites.siteField', 'Объект')}</Label>
              <Select value={engagementForm.site_id || '__none__'}
                onValueChange={(v) => setEngagementForm({
                  ...engagementForm, site_id: v === '__none__' ? '' : v,
                })}>
                <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="__none__">
                    {t('tasks.pages.sites.withoutSite', 'Без объекта')}
                  </SelectItem>
                  {sites.map((s) => (
                    <SelectItem key={s.id} value={String(s.id)}>{s.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>{t('tasks.pages.list.table.project', 'Проект')}</Label>
              <Select value={engagementForm.project_id || '__none__'}
                onValueChange={(v) => setEngagementForm({
                  ...engagementForm, project_id: v === '__none__' ? '' : v,
                })}>
                <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="__none__">
                    {t('tasks.pages.list.standaloneOnly', 'Без проекта')}
                  </SelectItem>
                  {projects.map((p) => (
                    <SelectItem key={p.id} value={String(p.id)}>{p.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>{t('tasks.pages.contractors.contractNo', 'Договор')}</Label>
                <Input value={engagementForm.contract_no} className="mt-1"
                  onChange={(e) => setEngagementForm({ ...engagementForm, contract_no: e.target.value })} />
              </div>
              <div>
                <Label>{t('tasks.projects.start', 'Начало')}</Label>
                <Input type="date" value={engagementForm.start_date} className="mt-1"
                  onChange={(e) => setEngagementForm({ ...engagementForm, start_date: e.target.value })} />
              </div>
            </div>
            <div>
              <Label>{t('tasks.projects.end', 'Завершение')}</Label>
              <Input type="date" value={engagementForm.end_date} className="mt-1"
                onChange={(e) => setEngagementForm({ ...engagementForm, end_date: e.target.value })} />
            </div>
            <div>
              <Label>{t('tasks.pages.contractors.scope', 'Вид работ')}</Label>
              <Textarea value={engagementForm.scope} rows={3} className="mt-1"
                onChange={(e) => setEngagementForm({ ...engagementForm, scope: e.target.value })} />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEngagementDialog(false)}>
              {t('common.cancel', 'Отмена')}
            </Button>
            <Button onClick={() => engagementMutation.mutate(engagementForm)}
              disabled={(!engagementForm.site_id && !engagementForm.project_id)
                || engagementMutation.isPending}>
              {t('common.add', 'Добавить')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </TasksLayout>
  );
};

export default HRContractors;
