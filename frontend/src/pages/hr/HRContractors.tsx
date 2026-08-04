import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { TasksLayout } from '@/components/tasks/TasksLayout';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { BinIinInput } from '@/components/ui/bin-iin-input';
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
  AlertCircle, Check, Edit, HardHat, MapPin, Plus, Search, Trash2, UserMinus, Users,
  Building2, Phone, Mail, FileText, CheckCircle2,
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
  active: 'bg-emerald-500 text-white',
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
    queryKey: ['contractor-engagements', selectedId],
    queryFn: () => fetchEngagements({ contractor_id: selectedId! }),
    enabled: selectedId !== null,
  });

  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => fetchProjects(),
  });

  const { data: sites = [] } = useQuery({
    queryKey: ['sites'],
    queryFn: () => fetchSites(),
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['contractors'] });
    if (selectedId) {
      queryClient.invalidateQueries({ queryKey: ['contractor-workers', selectedId] });
      queryClient.invalidateQueries({ queryKey: ['contractor-engagements', selectedId] });
    }
  };

  const fail = (labelKey: string, fallback: string) => (err: unknown) => {
    const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
    toast.error(typeof detail === 'string' ? detail : t(labelKey, fallback));
  };

  const contractorMutation = useMutation({
    mutationFn: (payload: typeof emptyContractor) => {
      const body = {
        name: payload.name.trim(),
        short_name: payload.short_name.trim() || null,
        bin_iin: payload.bin_iin.trim() || null,
        contact_person: payload.contact_person.trim() || null,
        phone: payload.phone.trim() || null,
        email: payload.email.trim() || null,
        address: payload.address.trim() || null,
        notes: payload.notes.trim() || null,
        status: payload.status,
      };
      return editingContractor
        ? updateContractor(editingContractor.id, body)
        : createContractor(body);
    },
    onSuccess: (saved) => {
      invalidate();
      setContractorDialog(false);
      if (!editingContractor) setSelectedId(saved.id);
      toast.success(t('tasks.pages.contractors.saved', 'Подрядчик сохранён'));
    },
    onError: fail('tasks.pages.contractors.saveError', 'Не удалось сохранить'),
  });

  const deleteContractorMutation = useMutation({
    mutationFn: (id: number) => deleteContractor(id),
    onSuccess: () => {
      if (selectedId === editingContractor?.id) setSelectedId(null);
      invalidate();
      toast.success(t('tasks.pages.contractors.deleted', 'Подрядчик удалён'));
    },
    onError: fail('tasks.pages.contractors.deleteError', 'Не удалось удалить'),
  });

  const workerMutation = useMutation({
    mutationFn: (payload: typeof emptyWorker) => {
      const body = {
        contractor_id: selectedId!,
        last_name: payload.last_name.trim(),
        first_name: payload.first_name.trim(),
        middle_name: payload.middle_name.trim() || null,
        phone: payload.phone.trim() || null,
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
      subtitle={t('tasks.pages.contractors.subtitle', 'Реестр субподрядных организаций, сотрудников и договоров')}
    >
      <div className="grid gap-6 lg:grid-cols-[minmax(0,360px)_minmax(0,1fr)] items-start">
        {/* ── Левая колонка: Список Подрядчиков ── */}
        <div className="rounded-3xl border bg-card p-4 shadow-2xs space-y-4 lg:sticky lg:top-24">
          <div className="flex items-center justify-between gap-2">
            <h2 className="text-sm font-bold text-foreground flex items-center gap-2">
              <HardHat className="h-4 w-4 text-primary" />
              {t('tasks.pages.contractors.title', 'Субподрядчики')} ({contractors.length})
            </h2>
            <Button
              size="sm"
              onClick={openCreateContractor}
              className="h-8 gap-1.5 rounded-xl bg-primary text-primary-foreground hover:bg-primary/90 font-semibold text-xs shadow-2xs"
            >
              <Plus className="h-3.5 w-3.5" />
              Добавить
            </Button>
          </div>

          <div className="space-y-2">
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
              <Input
                placeholder={t('tasks.pages.contractors.search', 'Поиск подрядчика…')}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pl-8 h-8 text-xs rounded-xl bg-muted/30"
              />
            </div>
            <Select value={statusFilter} onValueChange={setStatusFilter}>
              <SelectTrigger className="h-8 text-xs rounded-xl bg-muted/30">
                <SelectValue placeholder="Статус" />
              </SelectTrigger>
              <SelectContent className="rounded-2xl">
                <SelectItem value="all">{t('tasks.pages.contractors.allStatuses', 'Все статусы')}</SelectItem>
                {STATUSES.map((s) => (
                  <SelectItem key={s} value={s}>{statusLabel(s)}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {isLoading ? (
            <p className="text-xs text-muted-foreground py-6 text-center">{t('common.loading', 'Загрузка…')}</p>
          ) : error ? (
            <p className="flex items-center gap-2 text-red-500 py-6 justify-center text-xs">
              <AlertCircle className="h-4 w-4" />
              {t('tasks.pages.contractors.loadError', 'Ошибка загрузки')}
            </p>
          ) : contractors.length === 0 ? (
            <p className="text-xs text-muted-foreground py-6 text-center">
              {t('tasks.pages.contractors.empty', 'Подрядчики не найдены')}
            </p>
          ) : (
            <div className="space-y-2 max-h-[calc(100vh-280px)] overflow-y-auto pr-1">
              {contractors.map((c) => {
                const active = c.id === selectedId;
                return (
                  <div
                    key={c.id}
                    onClick={() => setSelectedId(c.id)}
                    className={`rounded-2xl border p-3 cursor-pointer transition-all duration-150 space-y-1.5 ${
                      active
                        ? 'bg-primary/10 border-primary shadow-2xs'
                        : 'bg-card/60 hover:bg-muted/40 border-border/60'
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="font-bold text-xs text-foreground truncate">{c.name}</div>
                      <Badge className={`text-[10px] px-1.5 py-0 rounded-md shrink-0 ${STATUS_BADGE[c.status]}`}>
                        {statusLabel(c.status)}
                      </Badge>
                    </div>
                    {c.bin_iin && (
                      <div className="text-[11px] text-muted-foreground font-mono">БИН/ИИН: {c.bin_iin}</div>
                    )}
                    <div className="flex items-center gap-3 text-[11px] text-muted-foreground">
                      <span>Людей: {c.workers_count}</span>
                      <span>Объектов: {c.engagements_count}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* ── Правая колонка: Детали Подрядчика ── */}
        <div className="space-y-6">
          {!selected ? (
            <div className="rounded-3xl border bg-card p-12 text-center text-muted-foreground text-xs space-y-2">
              <HardHat className="h-8 w-8 mx-auto text-muted-foreground/60" />
              <p>{t('tasks.pages.contractors.selectHint', 'Выберите подрядчика из списка слева для просмотра подробностей')}</p>
            </div>
          ) : (
            <>
              {/* Карточка подряда */}
              <div className="rounded-3xl border bg-card p-5 shadow-2xs space-y-4">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b pb-4">
                  <div>
                    <div className="flex items-center gap-2">
                      <h2 className="text-lg font-bold text-foreground">{selected.name}</h2>
                      <Badge className={`text-xs px-2 py-0.5 rounded-md ${STATUS_BADGE[selected.status]}`}>
                        {statusLabel(selected.status)}
                      </Badge>
                    </div>
                    {selected.short_name && (
                      <p className="text-xs text-muted-foreground mt-0.5">{selected.short_name}</p>
                    )}
                  </div>

                  <div className="flex items-center gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-8 gap-1.5 rounded-xl text-xs"
                      onClick={() => openEditContractor(selected)}
                    >
                      <Edit className="h-3.5 w-3.5" />
                      Редактировать
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-8 w-8 p-0 text-destructive hover:text-destructive rounded-xl"
                      onClick={() => {
                        if (confirm(t('tasks.pages.contractors.deleteConfirm', 'Удалить подрядчика?'))) {
                          deleteContractorMutation.mutate(selected.id);
                        }
                      }}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </div>

                <div className="grid gap-3 sm:grid-cols-2 md:grid-cols-3 text-xs">
                  {selected.bin_iin && (
                    <div className="space-y-0.5">
                      <div className="text-muted-foreground font-medium">БИН / ИИН</div>
                      <div className="font-mono font-semibold">{selected.bin_iin}</div>
                    </div>
                  )}
                  {selected.contact_person && (
                    <div className="space-y-0.5">
                      <div className="text-muted-foreground font-medium">Контактное лицо</div>
                      <div className="font-semibold">{selected.contact_person}</div>
                    </div>
                  )}
                  {selected.phone && (
                    <div className="space-y-0.5">
                      <div className="text-muted-foreground font-medium">Телефон</div>
                      <div className="font-semibold">{selected.phone}</div>
                    </div>
                  )}
                  {selected.email && (
                    <div className="space-y-0.5">
                      <div className="text-muted-foreground font-medium">Email</div>
                      <div className="font-semibold">{selected.email}</div>
                    </div>
                  )}
                  {selected.address && (
                    <div className="space-y-0.5 sm:col-span-2">
                      <div className="text-muted-foreground font-medium">Адрес</div>
                      <div className="font-semibold">{selected.address}</div>
                    </div>
                  )}
                </div>

                {selected.notes && (
                  <div className="pt-2 border-t text-xs text-muted-foreground">
                    <span className="font-medium text-foreground">Заметки: </span>{selected.notes}
                  </div>
                )}
              </div>

              {/* Привлечения на объекты */}
              <div className="rounded-3xl border bg-card p-5 shadow-2xs space-y-4">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-bold text-foreground flex items-center gap-2">
                    <MapPin className="h-4 w-4 text-primary" />
                    Привлечения на объекты ({engagements.length})
                  </h3>
                  <Button
                    size="sm"
                    onClick={() => { setEngagementForm(emptyEngagement); setEngagementDialog(true); }}
                    className="h-8 gap-1 rounded-xl bg-primary text-primary-foreground hover:bg-primary/90 text-xs font-semibold"
                  >
                    <Plus className="h-3.5 w-3.5" />
                    Назначить на объект
                  </Button>
                </div>

                {engagements.length === 0 ? (
                  <p className="text-xs text-muted-foreground text-center py-6">Подрядчик не привлечён ни к одному объекту</p>
                ) : (
                  <div className="overflow-x-auto">
                    <Table className="text-xs">
                      <TableHeader>
                        <TableRow>
                          <TableHead>Объект / Проект</TableHead>
                          <TableHead>Договор</TableHead>
                          <TableHead>Вид работ</TableHead>
                          <TableHead>Сроки</TableHead>
                          <TableHead className="w-[50px]"></TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {engagements.map((e) => (
                          <TableRow key={e.id}>
                            <TableCell className="font-medium">
                              {e.site_name || e.project_name || '—'}
                            </TableCell>
                            <TableCell className="font-mono text-muted-foreground">{e.contract_no || '—'}</TableCell>
                            <TableCell>{e.scope || '—'}</TableCell>
                            <TableCell className="text-muted-foreground">
                              {[e.start_date, e.end_date].filter(Boolean).join(' — ') || '—'}
                            </TableCell>
                            <TableCell className="text-right">
                              <Button
                                size="icon"
                                variant="ghost"
                                className="h-7 w-7 text-muted-foreground hover:text-destructive rounded-lg"
                                onClick={() => deleteEngagementMutation.mutate(e.id)}
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                              </Button>
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                )}
              </div>

              {/* Персонал подрядчика */}
              <div className="rounded-3xl border bg-card p-5 shadow-2xs space-y-4">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-bold text-foreground flex items-center gap-2">
                    <Users className="h-4 w-4 text-primary" />
                    Сотрудники подрядчика ({workers.length})
                  </h3>
                  <Button
                    size="sm"
                    onClick={openCreateWorker}
                    className="h-8 gap-1 rounded-xl bg-primary text-primary-foreground hover:bg-primary/90 text-xs font-semibold"
                  >
                    <Plus className="h-3.5 w-3.5" />
                    Добавить сотрудника
                  </Button>
                </div>

                {workers.length === 0 ? (
                  <p className="text-xs text-muted-foreground text-center py-6">Нет внесенных сотрудников</p>
                ) : (
                  <div className="overflow-x-auto">
                    <Table className="text-xs">
                      <TableHeader>
                        <TableRow>
                          <TableHead>ФИО</TableHead>
                          <TableHead>Должность</TableHead>
                          <TableHead>Уровень</TableHead>
                          <TableHead>Контакты</TableHead>
                          <TableHead className="w-[80px] text-right"></TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {workers.map((w) => (
                          <TableRow key={w.id} className={!w.is_active ? 'opacity-50' : ''}>
                            <TableCell className="font-semibold">
                              {[w.last_name, w.first_name, w.middle_name].filter(Boolean).join(' ')}
                            </TableCell>
                            <TableCell>{w.position_title || '—'}</TableCell>
                            <TableCell>
                              <Badge className={`text-[10px] px-1.5 py-0 rounded-md ${LEVEL_BADGE[w.level]}`}>
                                {levelLabel(w.level)}
                              </Badge>
                            </TableCell>
                            <TableCell className="text-muted-foreground">
                              {[w.phone, w.email].filter(Boolean).join(' • ') || '—'}
                            </TableCell>
                            <TableCell className="text-right">
                              <div className="flex justify-end gap-1">
                                <Button
                                  size="icon"
                                  variant="ghost"
                                  className="h-7 w-7 rounded-lg"
                                  onClick={() => openEditWorker(w)}
                                >
                                  <Edit className="h-3.5 w-3.5" />
                                </Button>
                                {w.is_active ? (
                                  <Button
                                    size="icon"
                                    variant="ghost"
                                    className="h-7 w-7 text-muted-foreground hover:text-destructive rounded-lg"
                                    onClick={() => deactivateWorkerMutation.mutate(w.id)}
                                    title="Отключить"
                                  >
                                    <UserMinus className="h-3.5 w-3.5" />
                                  </Button>
                                ) : (
                                  <Button
                                    size="icon"
                                    variant="ghost"
                                    className="h-7 w-7 text-muted-foreground hover:text-primary rounded-lg"
                                    onClick={() => restoreWorkerMutation.mutate(w.id)}
                                    title="Восстановить"
                                  >
                                    <Check className="h-3.5 w-3.5" />
                                  </Button>
                                )}
                              </div>
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </div>

      {/* Модальное окно создания / редактирования Подрядчика */}
      <Dialog open={contractorDialog} onOpenChange={setContractorDialog}>
        <DialogContent className="max-w-lg rounded-3xl">
          <DialogHeader>
            <DialogTitle>
              {editingContractor ? 'Редактирование подрядчика' : 'Новый подрядчик'}
            </DialogTitle>
          </DialogHeader>
          <div className="grid gap-3 text-xs">
            <div>
              <Label className="text-xs">Название компании *</Label>
              <Input
                value={contractorForm.name}
                onChange={(e) => setContractorForm({ ...contractorForm, name: e.target.value })}
                placeholder="ТОО «СтройГрупп»"
                className="h-8 rounded-xl bg-muted/30 mt-1"
              />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <Label className="text-xs">Короткое название</Label>
                <Input
                  value={contractorForm.short_name}
                  onChange={(e) => setContractorForm({ ...contractorForm, short_name: e.target.value })}
                  placeholder="СтройГрупп"
                  className="h-8 rounded-xl bg-muted/30 mt-1"
                />
              </div>
              <div>
                <Label className="text-xs">БИН / ИИН</Label>
                <BinIinInput
                  value={contractorForm.bin_iin}
                  onChange={(v) => setContractorForm({ ...contractorForm, bin_iin: v })}
                  className="h-8 rounded-xl bg-muted/30 mt-1"
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div>
                <Label className="text-xs">Контактное лицо</Label>
                <Input
                  value={contractorForm.contact_person}
                  onChange={(e) => setContractorForm({ ...contractorForm, contact_person: e.target.value })}
                  placeholder="Иван Иванов"
                  className="h-8 rounded-xl bg-muted/30 mt-1"
                />
              </div>
              <div>
                <Label className="text-xs">Статус</Label>
                <Select value={contractorForm.status} onValueChange={(val: ContractorStatus) => setContractorForm({ ...contractorForm, status: val })}>
                  <SelectTrigger className="h-8 rounded-xl bg-muted/30 mt-1">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="rounded-2xl">
                    {STATUSES.map((s) => (
                      <SelectItem key={s} value={s}>{statusLabel(s)}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div>
                <Label className="text-xs">Телефон</Label>
                <PhoneInput
                  value={contractorForm.phone}
                  onChange={(v) => setContractorForm({ ...contractorForm, phone: v })}
                />
              </div>
              <div>
                <Label className="text-xs">Email</Label>
                <Input
                  value={contractorForm.email}
                  onChange={(e) => setContractorForm({ ...contractorForm, email: e.target.value })}
                  placeholder="info@stroy.kz"
                  className="h-8 rounded-xl bg-muted/30 mt-1"
                />
              </div>
            </div>

            <div>
              <Label className="text-xs">Адрес</Label>
              <Input
                value={contractorForm.address}
                onChange={(e) => setContractorForm({ ...contractorForm, address: e.target.value })}
                className="h-8 rounded-xl bg-muted/30 mt-1"
              />
            </div>

            <div>
              <Label className="text-xs">Заметки</Label>
              <Textarea
                value={contractorForm.notes}
                onChange={(e) => setContractorForm({ ...contractorForm, notes: e.target.value })}
                className="rounded-xl bg-muted/30 mt-1 text-xs"
              />
            </div>
          </div>
          <DialogFooter className="mt-4 gap-2">
            <Button variant="outline" className="rounded-xl text-xs" onClick={() => setContractorDialog(false)}>
              Отмена
            </Button>
            <Button
              className="rounded-xl text-xs bg-primary"
              disabled={!contractorForm.name.trim() || contractorMutation.isPending}
              onClick={() => contractorMutation.mutate(contractorForm)}
            >
              Сохранить
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Модальное окно Назначение на объект */}
      <Dialog open={engagementDialog} onOpenChange={setEngagementDialog}>
        <DialogContent className="max-w-md rounded-3xl">
          <DialogHeader>
            <DialogTitle>Назначение подрядчика на объект</DialogTitle>
          </DialogHeader>
          <div className="grid gap-3 text-xs">
            <div>
              <Label className="text-xs">Объект / Площадка</Label>
              <Select value={engagementForm.site_id} onValueChange={(val) => setEngagementForm({ ...engagementForm, site_id: val })}>
                <SelectTrigger className="h-8 rounded-xl bg-muted/30 mt-1">
                  <SelectValue placeholder="Выберите объект..." />
                </SelectTrigger>
                <SelectContent className="rounded-2xl">
                  {sites.map((s) => (
                    <SelectItem key={s.id} value={String(s.id)}>{s.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div>
              <Label className="text-xs">Проект</Label>
              <Select value={engagementForm.project_id} onValueChange={(val) => setEngagementForm({ ...engagementForm, project_id: val })}>
                <SelectTrigger className="h-8 rounded-xl bg-muted/30 mt-1">
                  <SelectValue placeholder="Выберите проект..." />
                </SelectTrigger>
                <SelectContent className="rounded-2xl">
                  {projects.map((p) => (
                    <SelectItem key={p.id} value={String(p.id)}>{p.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div>
              <Label className="text-xs">Номер договора</Label>
              <Input
                value={engagementForm.contract_no}
                onChange={(e) => setEngagementForm({ ...engagementForm, contract_no: e.target.value })}
                placeholder="ДГ-2026/01"
                className="h-8 rounded-xl bg-muted/30 mt-1 font-mono"
              />
            </div>

            <div>
              <Label className="text-xs">Вид выполняемых работ</Label>
              <Input
                value={engagementForm.scope}
                onChange={(e) => setEngagementForm({ ...engagementForm, scope: e.target.value })}
                placeholder="Монолитные работы, кладка…"
                className="h-8 rounded-xl bg-muted/30 mt-1"
              />
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div>
                <Label className="text-xs">Начало</Label>
                <Input
                  type="date"
                  value={engagementForm.start_date}
                  onChange={(e) => setEngagementForm({ ...engagementForm, start_date: e.target.value })}
                  className="h-8 rounded-xl bg-muted/30 mt-1"
                />
              </div>
              <div>
                <Label className="text-xs">Окончание</Label>
                <Input
                  type="date"
                  value={engagementForm.end_date}
                  onChange={(e) => setEngagementForm({ ...engagementForm, end_date: e.target.value })}
                  className="h-8 rounded-xl bg-muted/30 mt-1"
                />
              </div>
            </div>
          </div>
          <DialogFooter className="mt-4 gap-2">
            <Button variant="outline" className="rounded-xl text-xs" onClick={() => setEngagementDialog(false)}>
              Отмена
            </Button>
            <Button
              className="rounded-xl text-xs bg-primary"
              disabled={engagementMutation.isPending}
              onClick={() => engagementMutation.mutate(engagementForm)}
            >
              Сохранить
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Модальное окно Сотрудник подрядчика */}
      <Dialog open={workerDialog} onOpenChange={setWorkerDialog}>
        <DialogContent className="max-w-md rounded-3xl">
          <DialogHeader>
            <DialogTitle>
              {editingWorker ? 'Редактирование сотрудника' : 'Новый сотрудник подрядчика'}
            </DialogTitle>
          </DialogHeader>
          <div className="grid gap-3 text-xs">
            <div className="grid grid-cols-2 gap-2">
              <div>
                <Label className="text-xs">Фамилия *</Label>
                <Input
                  value={workerForm.last_name}
                  onChange={(e) => setWorkerForm({ ...workerForm, last_name: e.target.value })}
                  className="h-8 rounded-xl bg-muted/30 mt-1"
                />
              </div>
              <div>
                <Label className="text-xs">Имя *</Label>
                <Input
                  value={workerForm.first_name}
                  onChange={(e) => setWorkerForm({ ...workerForm, first_name: e.target.value })}
                  className="h-8 rounded-xl bg-muted/30 mt-1"
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div>
                <Label className="text-xs">Отчество</Label>
                <Input
                  value={workerForm.middle_name}
                  onChange={(e) => setWorkerForm({ ...workerForm, middle_name: e.target.value })}
                  className="h-8 rounded-xl bg-muted/30 mt-1"
                />
              </div>
              <div>
                <Label className="text-xs">Квалификация</Label>
                <Select value={workerForm.level} onValueChange={(val: ContractorLevel) => setWorkerForm({ ...workerForm, level: val })}>
                  <SelectTrigger className="h-8 rounded-xl bg-muted/30 mt-1">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="rounded-2xl">
                    {LEVELS.map((l) => (
                      <SelectItem key={l} value={l}>{levelLabel(l)}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div>
              <Label className="text-xs">Специальность / Должность</Label>
              <Input
                value={workerForm.position_title}
                onChange={(e) => setWorkerForm({ ...workerForm, position_title: e.target.value })}
                placeholder="Сварщик 5 разряда"
                className="h-8 rounded-xl bg-muted/30 mt-1"
              />
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div>
                <Label className="text-xs">Телефон</Label>
                <PhoneInput
                  value={workerForm.phone}
                  onChange={(v) => setWorkerForm({ ...workerForm, phone: v })}
                />
              </div>
              <div>
                <Label className="text-xs">Email</Label>
                <Input
                  value={workerForm.email}
                  onChange={(e) => setWorkerForm({ ...workerForm, email: e.target.value })}
                  className="h-8 rounded-xl bg-muted/30 mt-1"
                />
              </div>
            </div>
          </div>
          <DialogFooter className="mt-4 gap-2">
            <Button variant="outline" className="rounded-xl text-xs" onClick={() => setWorkerDialog(false)}>
              Отмена
            </Button>
            <Button
              className="rounded-xl text-xs bg-primary"
              disabled={!workerForm.last_name.trim() || !workerForm.first_name.trim() || workerMutation.isPending}
              onClick={() => workerMutation.mutate(workerForm)}
            >
              Сохранить
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </TasksLayout>
  );
};

export default HRContractors;
