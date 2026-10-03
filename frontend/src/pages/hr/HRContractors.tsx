import React, { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { PrerequisiteNotice } from '@/components/common/PrerequisiteNotice';
import { DateInput } from '@/components/ui/date-input';
import { DATES_OUT_OF_ORDER, INVALID_DATE, datesOutOfOrder } from '@/lib/validation';
import { reportApiError } from '@/lib/apiError';
import { TasksLayout } from '@/components/tasks/TasksLayout';
import { ContractorCounterpartyPicker } from '@/components/tasks/ContractorCounterpartyPicker';
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
  Building2, Phone, Mail, FileText, CheckCircle2, Link2, RefreshCw,
} from 'lucide-react';
import {
  createContractor, createContractorWorker, createEngagement,
  deactivateContractorWorker, deleteContractor, deleteEngagement,
  fetchContractors, fetchContractorWorkers, fetchEngagements,
  fetchProjects, fetchSites, searchContractorCounterparties, searchEngagementAgreements,
  updateContractor,
  updateContractorWorker,
} from '@/api/tasks';
import { COUNTERPARTIES_BASE } from '@/features/bpp/counterparties/api';
import type {
  Contractor, ContractorCounterpartyOption, ContractorCounterpartyRef, ContractorLevel,
  ContractorStatus, ContractorWorker,
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
  /** Контрагент модуля «Закупки и оплаты» (бейдж); `null` — не связан. */
  counterparty: null as ContractorCounterpartyRef | null,
};

type ContractorForm = typeof emptyContractor;

/** Форма БИН/ИИН партнёра (бэкенд: `^\d{12}$`). Иностранный номер
 *  контрагента другой формы партнёру не переносится — ему некуда лечь. */
const KZ_BIN_RE = /^\d{12}$/;

/** Бейдж контрагента — то, что хранит форма и показывает выбор. */
const refOf = (cp: ContractorCounterpartyOption): ContractorCounterpartyRef => ({
  id: cp.id, name: cp.name, reg_number: cp.reg_number, status: cp.status,
});

/**
 * Подтянуть реквизиты контрагента в форму партнёра.
 *
 * `overwrite=false` — при выборе контрагента: заполняются только пустые
 * поля, чтобы не затереть то, что уже вписали руками (прораб на объекте не
 * обязан совпадать с директором из карточки контрагента). `overwrite=true` —
 * по явной кнопке «Подтянуть реквизиты».
 */
const fillFromCounterparty = (
  form: ContractorForm, cp: ContractorCounterpartyOption, overwrite: boolean,
): ContractorForm => {
  const next = { ...form, counterparty: refOf(cp) };
  const pairs: [keyof ContractorForm, string][] = [
    ['name', cp.name],
    ['contact_person', cp.contact_person],
    ['phone', cp.phone],
    ['email', cp.email],
    ['address', cp.legal_address],
  ];
  if (KZ_BIN_RE.test(cp.reg_number)) pairs.push(['bin_iin', cp.reg_number]);
  for (const [key, value] of pairs) {
    if (value && (overwrite || !String(next[key] ?? '').trim())) {
      (next as Record<string, unknown>)[key] = value;
    }
  }
  return next;
};

const emptyWorker = {
  last_name: '', first_name: '', middle_name: '', phone: '', email: '',
  position_title: '', level: 'junior' as ContractorLevel,
};

const emptyEngagement = {
  project_id: '', site_id: '', contract_no: '', bpp_agreement_id: '', scope: '',
  start_date: '', end_date: '',
};

/** Статус контрагента модуля — подпись бейджа. */
const COUNTERPARTY_STATUS_FALLBACK: Record<string, string> = {
  active: 'Активен', blocked: 'Заблокирован', archived: 'Архив',
};

const HRContractors: React.FC = () => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const [searchParams] = useSearchParams();
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  // `?id=` — сюда ведёт ссылка «партнёр на объектах» из карточки контрагента.
  const [selectedId, setSelectedId] = useState<number | null>(() => {
    const fromUrl = Number(searchParams.get('id'));
    return Number.isInteger(fromUrl) && fromUrl > 0 ? fromUrl : null;
  });

  const [contractorDialog, setContractorDialog] = useState(false);
  const [editingContractor, setEditingContractor] = useState<Contractor | null>(null);
  const [contractorForm, setContractorForm] = useState(emptyContractor);
  // Строка поиска, выбранная в этой сессии формы: по ней работает кнопка
  // «Подтянуть все реквизиты заново» (у бейджа из ответа контактов нет).
  const [pickedCounterparty, setPickedCounterparty] =
    useState<ContractorCounterpartyOption | null>(null);

  const [workerDialog, setWorkerDialog] = useState(false);
  const [editingWorker, setEditingWorker] = useState<ContractorWorker | null>(null);
  const [workerForm, setWorkerForm] = useState(emptyWorker);

  const [engagementDialog, setEngagementDialog] = useState(false);
  const [agreementQuery, setAgreementQuery] = useState('');
  const [pickedAgreement, setPickedAgreement] = useState<{ id: string; label: string } | null>(null);
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

  // Договоры модуля — только у партнёра, связанного с контрагентом, и пока
  // открыт диалог привлечения. Права на договоры решает сервер: нет права —
  // пустой список, и остаётся ввод номера текстом.
  const { data: agreementOptions = [] } = useQuery({
    queryKey: ['contractor-engagement-agreements', selectedId, agreementQuery.trim()],
    queryFn: () => searchEngagementAgreements(selectedId!, agreementQuery.trim() || undefined),
    enabled: engagementDialog && selectedId !== null && Boolean(selected?.bpp_counterparty_id),
    retry: false,
  });

  const { data: engagements = [] } = useQuery({
    queryKey: ['contractor-engagements', selectedId],
    queryFn: () => fetchEngagements({ contractor_id: selectedId! }),
    enabled: selectedId !== null,
  });

  const { data: projects = [], isLoading: projectsLoading } = useQuery({
    queryKey: ['projects'],
    queryFn: () => fetchProjects(),
  });

  const { data: sites = [], isLoading: sitesLoading } = useQuery({
    queryKey: ['sites'],
    queryFn: () => fetchSites(),
  });

  // Несвязанный партнёр с БИН, под которым в модуле закупок есть
  // действующий контрагент, — почти наверняка одна организация, заведённая
  // дважды. Отказ поиска (модуль выключен) здесь не сообщается: подсказка
  // необязательна, а экран партнёров должен работать и без модуля.
  const suggestionBin = selected && !selected.bpp_counterparty_id ? selected.bin_iin ?? '' : '';
  const suggestionQuery = useQuery({
    queryKey: ['contractors', 'counterparty-search', 'by-bin', suggestionBin],
    queryFn: () => searchContractorCounterparties(suggestionBin, 5),
    enabled: Boolean(suggestionBin),
    retry: false,
    staleTime: 60_000,
  });
  const suggestedCounterparty = suggestionBin
    ? (suggestionQuery.data ?? []).find((cp) => cp.reg_number === suggestionBin) ?? null
    : null;

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['contractors'] });
    if (selectedId) {
      queryClient.invalidateQueries({ queryKey: ['contractor-workers', selectedId] });
      queryClient.invalidateQueries({ queryKey: ['contractor-engagements', selectedId] });
    }
  };

  const fail = (labelKey: string, fallback: string) => (err: unknown) => {
    reportApiError(err, t(labelKey, fallback));
  };

  const contractorMutation = useMutation({
    mutationFn: (payload: ContractorForm) => {
      const body: Partial<Contractor> = {
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
      // Связь отправляется, только если её тронули: иначе форма, открытая
      // при выключенном модуле закупок, не могла бы сохранить даже телефон.
      const counterpartyId = payload.counterparty?.id ?? null;
      if (counterpartyId !== (editingContractor?.bpp_counterparty_id ?? null)) {
        body.bpp_counterparty_id = counterpartyId;
      }
      return editingContractor
        ? updateContractor(editingContractor.id, body)
        : createContractor(body);
    },
    onSuccess: (saved) => {
      invalidate();
      setContractorDialog(false);
      if (!editingContractor) setSelectedId(saved.id);
      toast.success(t('tasks.pages.contractors.saved', 'Партнёр сохранён'));
    },
    onError: fail('tasks.pages.contractors.saveError', 'Не удалось сохранить'),
  });

  const linkCounterpartyMutation = useMutation({
    mutationFn: ({ contractorId, counterpartyId }: { contractorId: number; counterpartyId: string }) =>
      updateContractor(contractorId, { bpp_counterparty_id: counterpartyId }),
    onSuccess: () => {
      invalidate();
      toast.success(t('tasks.pages.contractors.counterpartyLinked', 'Партнёр связан с контрагентом'));
    },
    onError: fail('tasks.pages.contractors.saveError', 'Не удалось сохранить'),
  });

  const deleteContractorMutation = useMutation({
    mutationFn: (id: number) => deleteContractor(id),
    onSuccess: () => {
      if (selectedId === editingContractor?.id) setSelectedId(null);
      invalidate();
      toast.success(t('tasks.pages.contractors.deleted', 'Партнёр удалён'));
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

  const reversedEngagementDates = datesOutOfOrder(
    engagementForm.start_date, engagementForm.end_date);
  const [brokenEngagementDates, setBrokenEngagementDates] = useState(
    { start: false, end: false });
  const hasBrokenEngagementDate = brokenEngagementDates.start || brokenEngagementDates.end;

  const engagementMutation = useMutation({
    mutationFn: (payload: typeof emptyEngagement) => createEngagement({
      contractor_id: selectedId!,
      project_id: payload.project_id ? Number(payload.project_id) : null,
      site_id: payload.site_id ? Number(payload.site_id) : null,
      contract_no: payload.bpp_agreement_id ? null : payload.contract_no.trim() || null,
      bpp_agreement_id: payload.bpp_agreement_id || null,
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
    setPickedCounterparty(null);
    setContractorDialog(true);
  };

  const openEditContractor = (c: Contractor) => {
    setEditingContractor(c);
    setContractorForm({
      name: c.name, short_name: c.short_name ?? '', bin_iin: c.bin_iin ?? '',
      contact_person: c.contact_person ?? '', phone: c.phone ?? '',
      email: c.email ?? '', address: c.address ?? '', notes: c.notes ?? '',
      status: c.status,
      // Связан, но модуль выключен (бейджа нет) — держим ключ, чтобы форма
      // не сняла связь молча: подпись «связан» вместо имени.
      counterparty: c.bpp_counterparty ?? (c.bpp_counterparty_id
        ? {
          id: c.bpp_counterparty_id,
          name: t('tasks.pages.contractors.counterpartyLinkedUnknown', 'Связан с контрагентом'),
          reg_number: '', status: '',
        }
        : null),
    });
    setPickedCounterparty(null);
    setContractorDialog(true);
  };

  const pickCounterparty = (cp: ContractorCounterpartyOption | null) => {
    setPickedCounterparty(cp);
    setContractorForm(cp
      ? fillFromCounterparty(contractorForm, cp, false)
      : { ...contractorForm, counterparty: null });
  };

  const counterpartyStatusLabel = (status: string) =>
    t(`tasks.pages.contractors.counterpartyStatus.${status}`,
      COUNTERPARTY_STATUS_FALLBACK[status] ?? status);

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
      title={t('tasks.pages.contractors.title', 'Партнёры')}
      subtitle={t('tasks.pages.contractors.subtitle', 'Реестр партнёрских организаций, сотрудников и договоров')}
    >
      <div className="grid gap-6 lg:grid-cols-[minmax(0,360px)_minmax(0,1fr)] items-start">
        {/* ── Левая колонка: Список Партнёров ── */}
        <div className="rounded-3xl border bg-card p-4 shadow-2xs space-y-4 lg:sticky lg:top-24">
          <div className="flex items-center justify-between gap-2">
            <h2 className="text-sm font-bold text-foreground flex items-center gap-2">
              <HardHat className="h-4 w-4 text-primary" />
              {t('tasks.pages.contractors.title', 'Партнёры')} ({contractors.length})
            </h2>
            <Button
              size="sm"
              onClick={openCreateContractor}
              className="h-8 gap-1.5 rounded-xl bg-primary text-primary-foreground hover:bg-primary/90 font-semibold text-xs shadow-2xs"
            >
              <Plus className="h-3.5 w-3.5" />
              {t('common.add')}
            </Button>
          </div>

          <div className="space-y-2">
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
              <Input
                placeholder={t('tasks.pages.contractors.search', 'Поиск партнёра…')}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pl-8 h-8 text-xs rounded-xl bg-muted/30"
              />
            </div>
            <Select value={statusFilter} onValueChange={setStatusFilter}>
              <SelectTrigger className="h-8 text-xs rounded-xl bg-muted/30">
                <SelectValue placeholder={t('contracts.columns.status')} />
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
              {t('tasks.pages.contractors.empty', 'Партнёры не найдены')}
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
                      <div className="text-[11px] text-muted-foreground font-mono">{t('tasks.pages.contractors.binValue', { value: c.bin_iin })}</div>
                    )}
                    <div className="flex items-center gap-3 text-[11px] text-muted-foreground">
                      <span>{t('tasks.pages.contractors.peopleCount', { count: c.workers_count })}</span>
                      <span>{t('tasks.pages.contractors.siteCount', { count: c.engagements_count })}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* ── Правая колонка: Детали Партнёра ── */}
        <div className="space-y-6">
          {!selected ? (
            <div className="rounded-3xl border bg-card p-12 text-center text-muted-foreground text-xs space-y-2">
              <HardHat className="h-8 w-8 mx-auto text-muted-foreground/60" />
              <p>{t('tasks.pages.contractors.selectHint', 'Выберите партнёра из списка слева для просмотра подробностей')}</p>
            </div>
          ) : (
            <>
              {/* Карточка партнёра */}
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
                      {t('common.edit')}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-8 w-8 p-0 text-destructive hover:text-destructive rounded-xl"
                      onClick={() => {
                        if (confirm(t('tasks.pages.contractors.deleteConfirm', { name: selected.name }))) {
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
                      <div className="text-muted-foreground font-medium">{t('contracts.counterparty.bin')}</div>
                      <div className="font-mono font-semibold">{selected.bin_iin}</div>
                    </div>
                  )}
                  {selected.contact_person && (
                    <div className="space-y-0.5">
                      <div className="text-muted-foreground font-medium">{t('tasks.pages.contractors.contactPerson')}</div>
                      <div className="font-semibold">{selected.contact_person}</div>
                    </div>
                  )}
                  {selected.phone && (
                    <div className="space-y-0.5">
                      <div className="text-muted-foreground font-medium">{t('profile.phone')}</div>
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
                      <div className="text-muted-foreground font-medium">{t('contracts.counterparty.address')}</div>
                      <div className="font-semibold">{selected.address}</div>
                    </div>
                  )}
                </div>

                {selected.notes && (
                  <div className="pt-2 border-t text-xs text-muted-foreground">
                    <span className="font-medium text-foreground">{t('tasks.pages.contractors.notesLabel')} </span>{selected.notes}
                  </div>
                )}

                {/* Та же организация в модуле «Закупки и оплаты». Связанный
                    партнёр ведёт на карточку контрагента; несвязанный — либо
                    на найденного по БИН, либо в форму выбора. */}
                <div className="pt-3 border-t flex flex-wrap items-center justify-between gap-2 text-xs">
                  {selected.bpp_counterparty ? (
                    <div className="flex flex-wrap items-center gap-2 min-w-0">
                      <Link2 className="h-3.5 w-3.5 text-primary shrink-0" />
                      <span className="text-muted-foreground">{t('tasks.pages.contractors.counterpartyLabel', 'Контрагент в «Закупках и оплатах»:')}</span>
                      <Link
                        to={`${COUNTERPARTIES_BASE}/${selected.bpp_counterparty.id}`}
                        className="font-semibold truncate hover:underline underline-offset-2"
                      >
                        {selected.bpp_counterparty.name}
                      </Link>
                      <span className="font-mono text-muted-foreground">
                        {t('tasks.pages.contractors.counterpartyBin', 'БИН/ИИН')} {selected.bpp_counterparty.reg_number}
                      </span>
                      <Badge
                        variant={selected.bpp_counterparty.status === 'active' ? 'secondary' : 'destructive'}
                        className="text-[10px] px-1.5 py-0 h-4 rounded"
                      >
                        {counterpartyStatusLabel(selected.bpp_counterparty.status)}
                      </Badge>
                    </div>
                  ) : selected.bpp_counterparty_id ? (
                    <div className="flex items-center gap-2 text-muted-foreground">
                      <Link2 className="h-3.5 w-3.5 shrink-0" />
                      {t('tasks.pages.contractors.counterpartyUnavailable', 'Связан с контрагентом, но модуль «Закупки и оплаты» сейчас недоступен')}
                    </div>
                  ) : suggestedCounterparty ? (
                    <>
                      <span className="text-muted-foreground">
                        {t('tasks.pages.contractors.counterpartyFoundByBin', {
                          name: suggestedCounterparty.name,
                          defaultValue: 'В «Закупках и оплатах» есть контрагент «{{name}}» с тем же БИН/ИИН',
                        })}
                      </span>
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-7 gap-1.5 rounded-xl text-xs"
                        disabled={linkCounterpartyMutation.isPending}
                        onClick={() => linkCounterpartyMutation.mutate({
                          contractorId: selected.id, counterpartyId: suggestedCounterparty.id,
                        })}
                      >
                        <Link2 className="h-3.5 w-3.5" />
                        {t('tasks.pages.contractors.linkCounterparty', 'Связать')}
                      </Button>
                    </>
                  ) : (
                    <>
                      <span className="text-muted-foreground">
                        {t('tasks.pages.contractors.counterpartyNone', 'Не связан с контрагентом в «Закупках и оплатах»')}
                      </span>
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-7 gap-1.5 rounded-xl text-xs"
                        onClick={() => openEditContractor(selected)}
                      >
                        <Link2 className="h-3.5 w-3.5" />
                        {t('tasks.pages.contractors.chooseCounterparty', 'Выбрать контрагента')}
                      </Button>
                    </>
                  )}
                </div>
              </div>

              {/* Привлечения на объекты */}
              <div className="rounded-3xl border bg-card p-5 shadow-2xs space-y-4">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-bold text-foreground flex items-center gap-2">
                    <MapPin className="h-4 w-4 text-primary" />
                    {t('tasks.pages.contractors.engagementsCount', { count: engagements.length })}
                  </h3>
                  <Button
                    size="sm"
                    onClick={() => { setEngagementForm(emptyEngagement); setAgreementQuery(''); setPickedAgreement(null); setEngagementDialog(true); }}
                    className="h-8 gap-1 rounded-xl bg-primary text-primary-foreground hover:bg-primary/90 text-xs font-semibold"
                  >
                    <Plus className="h-3.5 w-3.5" />
                    {t('tasks.pages.contractors.assignToSite')}
                  </Button>
                </div>

                {engagements.length === 0 ? (
                  <p className="text-xs text-muted-foreground text-center py-6">{t('tasks.pages.contractors.noEngagements')}</p>
                ) : (
                  <div className="overflow-x-auto">
                    <Table className="text-xs">
                      <TableHeader>
                        <TableRow>
                          <TableHead>{t('tasks.pages.contractors.siteProject')}</TableHead>
                          <TableHead>{t('tasks.pages.contractors.contractNo')}</TableHead>
                          <TableHead>{t('tasks.pages.contractors.scope')}</TableHead>
                          <TableHead>{t('tasks.pages.contractors.dates')}</TableHead>
                          <TableHead className="w-[50px]"></TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {engagements.map((e) => (
                          <TableRow key={e.id}>
                            <TableCell className="font-medium">
                              {e.site_name || e.project_name || '—'}
                            </TableCell>
                            <TableCell className="font-mono text-muted-foreground">
                              {e.bpp_agreement ? (
                                <Link
                                  to={`/bpp/agreements/${e.bpp_agreement.id}`}
                                  className="text-foreground hover:underline underline-offset-2"
                                >
                                  {e.bpp_agreement.number}
                                </Link>
                              ) : e.agreement ? (
                                <Link
                                  to={`/contracts/agreements/${e.agreement.id}`}
                                  title={e.agreement.name}
                                  className="text-foreground hover:underline underline-offset-2"
                                >
                                  {e.agreement.number}
                                </Link>
                              ) : (e.contract_no || '—')}
                            </TableCell>
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

              {/* Персонал партнёра */}
              <div className="rounded-3xl border bg-card p-5 shadow-2xs space-y-4">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-bold text-foreground flex items-center gap-2">
                    <Users className="h-4 w-4 text-primary" />
                    {t('tasks.pages.contractors.workersCount', { count: workers.length })}
                  </h3>
                  <Button
                    size="sm"
                    onClick={openCreateWorker}
                    className="h-8 gap-1 rounded-xl bg-primary text-primary-foreground hover:bg-primary/90 text-xs font-semibold"
                  >
                    <Plus className="h-3.5 w-3.5" />
                    {t('tasks.pages.contractors.addWorker')}
                  </Button>
                </div>

                {workers.length === 0 ? (
                  <p className="text-xs text-muted-foreground text-center py-6">{t('tasks.pages.contractors.noWorkers')}</p>
                ) : (
                  <div className="overflow-x-auto">
                    <Table className="text-xs">
                      <TableHeader>
                        <TableRow>
                          <TableHead>{t('tasks.pages.contractors.fio')}</TableHead>
                          <TableHead>{t('tasks.pages.contractors.position')}</TableHead>
                          <TableHead>{t('tasks.pages.contractors.level.title')}</TableHead>
                          <TableHead>{t('tasks.pages.contractors.contacts')}</TableHead>
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
                                    title={t('tasks.pages.contractors.deactivate')}
                                  >
                                    <UserMinus className="h-3.5 w-3.5" />
                                  </Button>
                                ) : (
                                  <Button
                                    size="icon"
                                    variant="ghost"
                                    className="h-7 w-7 text-muted-foreground hover:text-primary rounded-lg"
                                    onClick={() => restoreWorkerMutation.mutate(w.id)}
                                    title={t('tasks.pages.contractors.restore')}
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

      {/* Модальное окно создания / редактирования Партнёра */}
      <Dialog open={contractorDialog} onOpenChange={setContractorDialog}>
        <DialogContent className="max-w-lg rounded-3xl">
          <DialogHeader>
            <DialogTitle>
              {editingContractor ? t('tasks.pages.contractors.editTitle') : t('tasks.pages.contractors.newTitle')}
            </DialogTitle>
          </DialogHeader>
          <div className="grid gap-3 text-xs">
            <div className="rounded-2xl border border-dashed p-3 space-y-2">
              <Label className="text-xs" htmlFor="contractor-counterparty">
                {t('tasks.pages.contractors.counterpartyPick', 'Контрагент из «Закупок и оплат»')}
              </Label>
              <div className="flex items-center gap-2">
                <ContractorCounterpartyPicker
                  id="contractor-counterparty"
                  value={contractorForm.counterparty}
                  onChange={pickCounterparty}
                />
                {pickedCounterparty && (
                  <Button
                    type="button"
                    size="icon"
                    variant="outline"
                    className="h-8 w-8 shrink-0 rounded-xl"
                    title={t('tasks.pages.contractors.counterpartyRefill', 'Подтянуть все реквизиты контрагента заново')}
                    onClick={() => setContractorForm(fillFromCounterparty(contractorForm, pickedCounterparty, true))}
                  >
                    <RefreshCw className="h-3.5 w-3.5" />
                  </Button>
                )}
              </div>
              <p className="text-[11px] text-muted-foreground">
                {t('tasks.pages.contractors.counterpartyHint', 'Та же организация в реестре контрагентов «Закупок и оплат»: при выборе пустые поля заполнятся из её карточки. Предлагаются только действующие контрагенты.')}
              </p>
            </div>
            <div>
              <Label className="text-xs">{t('tasks.pages.contractors.companyNameRequired')}</Label>
              <Input
                value={contractorForm.name}
                onChange={(e) => setContractorForm({ ...contractorForm, name: e.target.value })}
                placeholder={t('tasks.pages.contractors.namePlaceholder')}
                className="h-8 rounded-xl bg-muted/30 mt-1"
              />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <Label className="text-xs">{t('tasks.pages.contractors.shortName')}</Label>
                <Input
                  value={contractorForm.short_name}
                  onChange={(e) => setContractorForm({ ...contractorForm, short_name: e.target.value })}
                  placeholder={t('tasks.pages.contractors.shortPlaceholder')}
                  className="h-8 rounded-xl bg-muted/30 mt-1"
                />
              </div>
              <div>
                <Label className="text-xs">{t('contracts.counterparty.bin')}</Label>
                <BinIinInput
                  value={contractorForm.bin_iin}
                  onChange={(v) => setContractorForm({ ...contractorForm, bin_iin: v })}
                  className="h-8 rounded-xl bg-muted/30 mt-1"
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div>
                <Label className="text-xs">{t('tasks.pages.contractors.contactPerson')}</Label>
                <Input
                  value={contractorForm.contact_person}
                  onChange={(e) => setContractorForm({ ...contractorForm, contact_person: e.target.value })}
                  placeholder={t('tasks.pages.contractors.contactPlaceholder')}
                  className="h-8 rounded-xl bg-muted/30 mt-1"
                />
              </div>
              <div>
                <Label className="text-xs">{t('contracts.columns.status')}</Label>
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
                <Label className="text-xs">{t('profile.phone')}</Label>
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
              <Label className="text-xs">{t('contracts.counterparty.address')}</Label>
              <Input
                value={contractorForm.address}
                onChange={(e) => setContractorForm({ ...contractorForm, address: e.target.value })}
                className="h-8 rounded-xl bg-muted/30 mt-1"
              />
            </div>

            <div>
              <Label className="text-xs">{t('tasks.pages.contractors.notes')}</Label>
              <Textarea
                value={contractorForm.notes}
                onChange={(e) => setContractorForm({ ...contractorForm, notes: e.target.value })}
                className="rounded-xl bg-muted/30 mt-1 text-xs"
              />
            </div>
          </div>
          <DialogFooter className="mt-4 gap-2">
            <Button variant="outline" className="rounded-xl text-xs" onClick={() => setContractorDialog(false)}>
              {t('common.cancel')}
            </Button>
            <Button
              className="rounded-xl text-xs bg-primary"
              disabled={!contractorForm.name.trim() || contractorMutation.isPending}
              onClick={() => contractorMutation.mutate(contractorForm)}
            >
              {t('common.save')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Модальное окно Назначение на объект */}
      <Dialog open={engagementDialog} onOpenChange={setEngagementDialog}>
        <DialogContent className="max-w-md rounded-3xl">
          <DialogHeader>
            <DialogTitle>{t('tasks.pages.contractors.assignTitle')}</DialogTitle>
          </DialogHeader>
          <div className="grid gap-3 text-xs">
            <div>
              <Label className="text-xs">{t('tasks.pages.contractors.siteLocation')}</Label>
              <Select value={engagementForm.site_id} onValueChange={(val) => setEngagementForm({ ...engagementForm, site_id: val })}>
                <SelectTrigger className="h-8 rounded-xl bg-muted/30 mt-1">
                  <SelectValue placeholder={t('tasks.pages.contractors.pickSite')} />
                </SelectTrigger>
                <SelectContent className="rounded-2xl">
                  {sites.map((s) => (
                    <SelectItem key={s.id} value={String(s.id)}>{s.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {/* Объекты и проекты ведутся на своих страницах: пустой
                  список здесь — не сбой окна, а незаполненный справочник. */}
              <PrerequisiteNotice
                variant="inline"
                items={[{
                  when: !sitesLoading && sites.length === 0,
                  text: t('tasks.pages.sites.registryEmpty', 'Справочник объектов пуст —'),
                  to: '/tasks/sites',
                  linkText: t('tasks.pages.sites.addFirst', 'заведите объект'),
                }]}
              />
            </div>

            <div>
              <Label className="text-xs">{t('tasks.pages.contractors.project')}</Label>
              <Select value={engagementForm.project_id} onValueChange={(val) => setEngagementForm({ ...engagementForm, project_id: val })}>
                <SelectTrigger className="h-8 rounded-xl bg-muted/30 mt-1">
                  <SelectValue placeholder={t('tasks.pages.contractors.pickProject')} />
                </SelectTrigger>
                <SelectContent className="rounded-2xl">
                  {projects.map((p) => (
                    <SelectItem key={p.id} value={String(p.id)}>{p.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <PrerequisiteNotice
                variant="inline"
                items={[{
                  when: !projectsLoading && projects.length === 0,
                  text: t('tasks.projects.registryEmpty', 'Проектов пока нет —'),
                  to: '/manage/projects',
                  linkText: t('tasks.projects.addFirst', 'создайте проект'),
                }]}
              />
            </div>

            {/* Договор модуля «Закупки и оплаты» (M-5): выбор из договоров
                контрагента партнёра, номер ДГ-… ставит сервер. Выбор договора
                из «Договоров» снят (A6.1), старые привязки остаются ссылками
                в списке. Без выбора номер — свободным текстом. */}
            {(agreementOptions.length > 0 || agreementQuery.trim() !== ''
              || engagementForm.bpp_agreement_id !== '') && (
              <div>
                <Label className="text-xs">
                  {t('tasks.pages.contractors.bppAgreement', 'Договор модуля «Закупки и оплаты»')}
                </Label>
                {/* Поиск по номеру, номеру по документу и наименованию (от 2 символов) —
                    список сервера не ограничен последними договорами. */}
                <Input
                  value={agreementQuery}
                  onChange={(e) => setAgreementQuery(e.target.value)}
                  placeholder={t('tasks.pages.contractors.bppAgreementSearch', 'Найти договор по номеру или названию')}
                  aria-label={t('tasks.pages.contractors.bppAgreementSearch', 'Найти договор по номеру или названию')}
                  className="h-8 rounded-xl bg-muted/30 mt-1"
                />
                <Select
                  value={engagementForm.bpp_agreement_id || 'none'}
                  onValueChange={(val) => {
                    const option = agreementOptions.find((o) => o.id === val);
                    setPickedAgreement(option ? { id: option.id, label: option.number } : null);
                    setEngagementForm({
                      ...engagementForm, bpp_agreement_id: val === 'none' ? '' : val,
                    });
                  }}
                >
                  <SelectTrigger className="h-8 rounded-xl bg-muted/30 mt-1">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">
                      {t('tasks.pages.contractors.noBppAgreement', 'Не выбран')}
                    </SelectItem>
                    {pickedAgreement && !agreementOptions.some((o) => o.id === pickedAgreement.id) && (
                      <SelectItem value={pickedAgreement.id}>{pickedAgreement.label}</SelectItem>
                    )}
                    {agreementOptions.map((option) => (
                      <SelectItem key={option.id} value={option.id}>
                        {[option.number, option.ext_number && `№${option.ext_number}`, option.name]
                          .filter(Boolean).join(' · ')}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
            <div>
              <Label className="text-xs">{t('tasks.pages.contractors.contractNumber')}</Label>
              <Input
                value={engagementForm.contract_no}
                disabled={Boolean(engagementForm.bpp_agreement_id)}
                onChange={(e) => setEngagementForm({ ...engagementForm, contract_no: e.target.value })}
                placeholder={t('tasks.pages.contractors.contractPlaceholder')}
                className="h-8 rounded-xl bg-muted/30 mt-1 font-mono"
              />
            </div>

            <div>
              <Label className="text-xs">{t('tasks.pages.contractors.workKind')}</Label>
              <Input
                value={engagementForm.scope}
                onChange={(e) => setEngagementForm({ ...engagementForm, scope: e.target.value })}
                placeholder={t('tasks.pages.contractors.workPlaceholder')}
                className="h-8 rounded-xl bg-muted/30 mt-1"
              />
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div>
                <Label className="text-xs">{t('tasks.pages.contractors.start')}</Label>
                <DateInput
                  value={engagementForm.start_date}
                  invalid={brokenEngagementDates.start}
                  onValidityChange={(bad) => setBrokenEngagementDates((prev) => ({ ...prev, start: bad }))}
                  onChange={(value) => setEngagementForm({ ...engagementForm, start_date: value })}
                  className="h-8 rounded-xl bg-muted/30 mt-1"
                />
              </div>
              <div>
                <Label className="text-xs">{t('tasks.pages.contractors.end')}</Label>
                <DateInput
                  value={engagementForm.end_date}
                  invalid={brokenEngagementDates.end || reversedEngagementDates}
                  onValidityChange={(bad) => setBrokenEngagementDates((prev) => ({ ...prev, end: bad }))}
                  onChange={(value) => setEngagementForm({ ...engagementForm, end_date: value })}
                  className="h-8 rounded-xl bg-muted/30 mt-1"
                />
              </div>
            </div>
            {hasBrokenEngagementDate ? (
              <p className="mt-2 text-xs text-destructive">{INVALID_DATE}</p>
            ) : reversedEngagementDates && (
              <p className="mt-2 text-xs text-destructive">{DATES_OUT_OF_ORDER}</p>
            )}
          </div>
          <DialogFooter className="mt-4 gap-2">
            <Button variant="outline" className="rounded-xl text-xs" onClick={() => setEngagementDialog(false)}>
              {t('common.cancel')}
            </Button>
            <Button
              className="rounded-xl text-xs bg-primary"
              disabled={reversedEngagementDates || hasBrokenEngagementDate || engagementMutation.isPending}
              onClick={() => engagementMutation.mutate(engagementForm)}
            >
              {t('common.save')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Модальное окно Сотрудник партнёра */}
      <Dialog open={workerDialog} onOpenChange={setWorkerDialog}>
        <DialogContent className="max-w-md rounded-3xl">
          <DialogHeader>
            <DialogTitle>
              {editingWorker ? t('tasks.pages.contractors.editWorker') : t('tasks.pages.contractors.newWorker')}
            </DialogTitle>
          </DialogHeader>
          <div className="grid gap-3 text-xs">
            <div className="grid grid-cols-2 gap-2">
              <div>
                <Label className="text-xs">{t('tasks.pages.contractors.lastName')}</Label>
                <Input
                  value={workerForm.last_name}
                  onChange={(e) => setWorkerForm({ ...workerForm, last_name: e.target.value })}
                  className="h-8 rounded-xl bg-muted/30 mt-1"
                />
              </div>
              <div>
                <Label className="text-xs">{t('tasks.pages.contractors.firstName')}</Label>
                <Input
                  value={workerForm.first_name}
                  onChange={(e) => setWorkerForm({ ...workerForm, first_name: e.target.value })}
                  className="h-8 rounded-xl bg-muted/30 mt-1"
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div>
                <Label className="text-xs">{t('profile.patronymic')}</Label>
                <Input
                  value={workerForm.middle_name}
                  onChange={(e) => setWorkerForm({ ...workerForm, middle_name: e.target.value })}
                  className="h-8 rounded-xl bg-muted/30 mt-1"
                />
              </div>
              <div>
                <Label className="text-xs">{t('tasks.pages.contractors.qualification')}</Label>
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
              <Label className="text-xs">{t('tasks.pages.contractors.speciality')}</Label>
              <Input
                value={workerForm.position_title}
                onChange={(e) => setWorkerForm({ ...workerForm, position_title: e.target.value })}
                placeholder={t('tasks.pages.contractors.specialityPlaceholder')}
                className="h-8 rounded-xl bg-muted/30 mt-1"
              />
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div>
                <Label className="text-xs">{t('profile.phone')}</Label>
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
              {t('common.cancel')}
            </Button>
            <Button
              className="rounded-xl text-xs bg-primary"
              disabled={!workerForm.last_name.trim() || !workerForm.first_name.trim() || workerMutation.isPending}
              onClick={() => workerMutation.mutate(workerForm)}
            >
              {t('common.save')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </TasksLayout>
  );
};

export default HRContractors;
