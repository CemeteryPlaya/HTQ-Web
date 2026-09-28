/**
 * Реестр L-04 «План закупок» (ТЗ §08): позиции утверждённых заявок с
 * остатком к закупке. СН и ПМ отмечают свои позиции и нажимают «Оформить
 * договор» или «Оформить счёт»; ФД видит все позиции без действий.
 *
 * Своя таблица, а не `BppRegistry`: у плана флажок строки бывает недоступен
 * (остаток 0, ТЗ §8.3 п.2), кнопки документа зависят от состава выбора
 * (один проект и одна статья, §8.3 п.1), а у совмещающего СН и ПМ план
 * переключается по роли. Фильтры, страница и размер страницы помнятся так
 * же, как в остальных реестрах (`useRegistryState`).
 */
import { useEffect, useMemo, useState } from 'react';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';
import { ChevronLeft, ChevronRight, Download } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { reportApiError } from '@/lib/apiError';

import { exportRegistry } from '../core/registryExport';
import { FILTER_ALL, PAGE_SIZES, useRegistryState, type PageSize } from '../core/useRegistryState';
import { formatDate, formatMoney } from '../format';
import { projectApi, projectKeys } from '../projects/api';
import { bppRequestsApi, REQUESTS_BASE, type InitiatorRole } from '../requests/api';

import { PLAN_ENDPOINT, planApi, type PlanItem, type PlanSelection, type PlanTarget } from './api';
import { selectionProblem, shownQty } from './planSelection';
import { PlanWizardDialog } from './PlanWizardDialog';

const FILTER_KEYS = ['project_id', 'purchase_type', 'overdue'] as const;
const ROLE_TITLES: Record<InitiatorRole, string> = { sn: 'Снабжение', pm: 'Проектное управление' };

export function PlanPage() {
  const { t } = useTranslation();
  const state = useRegistryState('plan', {
    defaultSort: { field: 'need_date', desc: false },
    searchParam: 'search',
    filterKeys: FILTER_KEYS,
  });
  const me = useQuery({ queryKey: ['bpp', 'me'], queryFn: bppRequestsApi.me, staleTime: 60_000 });
  const roles = me.data?.initiator_roles ?? [];
  const [role, setRole] = useState<InitiatorRole | null>(null);
  const activeRole = role ?? roles[0] ?? null;

  const params = useMemo(
    () => ({ ...state.params, ...(activeRole ? { role: activeRole } : {}) }),
    [state.params, activeRole],
  );
  const { data, isLoading, isError } = useQuery({
    queryKey: ['bpp', 'registry', 'plan', params],
    queryFn: () => planApi.list(params),
    placeholderData: keepPreviousData,
    enabled: me.isSuccess,
  });
  const projects = useQuery({
    queryKey: projectKeys.list('', false),
    queryFn: () => projectApi.list('', false),
    staleTime: 5 * 60 * 1000,
  });

  const [selected, setSelected] = useState<Map<string, PlanItem>>(() => new Map());
  const [wizard, setWizard] = useState<PlanSelection | null>(null);
  const [checking, setChecking] = useState<PlanTarget | null>(null);
  const [exporting, setExporting] = useState(false);
  const paramsKey = JSON.stringify(params);
  useEffect(() => { setSelected(new Map()); }, [paramsKey]);

  const items = data?.items ?? [];
  const readOnly = data?.read_only ?? false;
  const total = data?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / state.pageSize));
  const problem = selectionProblem([...selected.values()]);

  const toggle = (item: PlanItem) => setSelected((current) => {
    const next = new Map(current);
    if (next.has(item.id)) next.delete(item.id);
    else next.set(item.id, item);
    return next;
  });

  const open = async (target: PlanTarget) => {
    setChecking(target);
    try {
      setWizard(await planApi.validate([...selected.keys()], target, activeRole));
    } catch (error) {
      reportApiError(error, t('bpp.plan.validateFailed', 'Не удалось проверить выбор позиций'));
    } finally {
      setChecking(null);
    }
  };

  const doExport = async () => {
    setExporting(true);
    try {
      const selection = { ...state.selectionParams, ...(activeRole ? { role: activeRole } : {}) };
      const result = await exportRegistry(PLAN_ENDPOINT, selection, 'plan');
      if (result.kind === 'queued') {
        toast.info(t('bpp.registry.exportQueued', 'Выгрузка готовится, ссылка придёт уведомлением'));
      }
    } catch (error) {
      reportApiError(error, t('bpp.registry.exportFailed', 'Не удалось выгрузить реестр'));
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="space-y-4">
      <h2 className="text-2xl font-bold tracking-tight">{t('bpp.plan.title', 'План закупок')}</h2>

      <div className="flex flex-wrap items-end gap-3">
        {roles.length > 1 && (
          <div className="space-y-1">
            <span className="text-xs text-muted-foreground">{t('bpp.plan.role', 'Роль')}</span>
            <Select value={activeRole ?? undefined} onValueChange={(value) => setRole(value as InitiatorRole)}>
              <SelectTrigger className="w-56" aria-label={t('bpp.plan.role', 'Роль')}><SelectValue /></SelectTrigger>
              <SelectContent>
                {roles.map((value) => <SelectItem key={value} value={value}>{ROLE_TITLES[value]}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
        )}
        <Input
          className="w-64"
          value={state.search}
          placeholder={t('bpp.plan.search', 'Номер позиции или заявки')}
          aria-label={t('bpp.plan.search', 'Номер позиции или заявки')}
          onChange={(event) => state.setSearch(event.target.value)}
        />
        <Select
          value={state.filters.project_id ?? FILTER_ALL}
          onValueChange={(value) => state.setFilter('project_id', value)}
        >
          <SelectTrigger className="w-64" aria-label={t('bpp.plan.project', 'Проект')}><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value={FILTER_ALL}>{t('bpp.plan.allProjects', 'Все проекты')}</SelectItem>
            {(projects.data ?? []).map((p) => (
              <SelectItem key={p.id} value={p.id}>{`${p.code} — ${p.name}`}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <label className="flex items-center gap-2 text-sm">
          <Checkbox
            checked={state.filters.overdue === '1'}
            onCheckedChange={(checked) => state.setFilter('overdue', checked ? '1' : '')}
          />
          {t('bpp.plan.overdue', 'Просроченные')}
        </label>
        <div className="ml-auto flex gap-2">
          <Button variant="outline" size="sm" onClick={doExport} disabled={exporting}>
            <Download className="mr-1.5 h-4 w-4" />
            {t('bpp.registry.export', 'Экспорт')}
          </Button>
          {!readOnly && (
            <>
              <Button
                size="sm" disabled={Boolean(problem) || checking !== null}
                title={problem ?? undefined} onClick={() => open('contract')}
              >
                {t('bpp.plan.contract', 'Оформить договор')}
              </Button>
              <Button
                size="sm" variant="outline" disabled={Boolean(problem) || checking !== null}
                title={problem ?? undefined} onClick={() => open('invoice')}
              >
                {t('bpp.plan.invoice', 'Оформить счёт')}
              </Button>
            </>
          )}
        </div>
      </div>
      {!readOnly && selected.size > 0 && problem && (
        <p role="status" className="text-sm text-muted-foreground">{problem}</p>
      )}
      {readOnly && (
        <Badge variant="outline">{t('bpp.plan.readOnly', 'Все позиции — только просмотр')}</Badge>
      )}

      {isLoading || !me.isSuccess ? <Skeleton className="h-48 w-full" /> : isError ? (
        <p className="text-sm text-muted-foreground">{t('bpp.plan.loadFailed', 'Не удалось загрузить план закупок.')}</p>
      ) : (
        <div className="overflow-x-auto rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                {!readOnly && <TableHead className="w-10" />}
                <TableHead>{t('bpp.plan.position', 'Позиция')}</TableHead>
                <TableHead>{t('bpp.plan.project', 'Проект')}</TableHead>
                <TableHead>{t('bpp.plan.article', 'Статья')}</TableHead>
                <TableHead>{t('bpp.plan.name', 'Наименование')}</TableHead>
                <TableHead>{t('bpp.plan.uom', 'Ед.')}</TableHead>
                <TableHead className="text-right">{t('bpp.plan.qtyPlan', 'Кол-во план')}</TableHead>
                <TableHead className="text-right">{t('bpp.plan.qtyInvoices', 'Кол-во в счетах')}</TableHead>
                <TableHead className="text-right">{t('bpp.plan.qtyLeft', 'Остаток кол-во')}</TableHead>
                <TableHead className="text-right">{t('bpp.plan.amount', 'Сумма план')}</TableHead>
                <TableHead className="text-right">{t('bpp.plan.amountLeft', 'Остаток суммы')}</TableHead>
                <TableHead>{t('bpp.plan.needDate', 'Дата потребности')}</TableHead>
                {readOnly && <TableHead>{t('bpp.plan.executor', 'Исполнитель')}</TableHead>}
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.length === 0 && (
                <TableRow>
                  <TableCell colSpan={13} className="text-center text-muted-foreground">
                    {t('bpp.plan.empty', 'Позиций к закупке нет')}
                  </TableCell>
                </TableRow>
              )}
              {items.map((item) => (
                <TableRow key={item.id} data-testid="plan-item">
                  {!readOnly && (
                    <TableCell>
                      <Checkbox
                        checked={selected.has(item.id)}
                        disabled={!item.selectable}
                        aria-label={t('bpp.plan.select', 'Отметить {{n}}', { n: item.sys_number })}
                        onCheckedChange={() => toggle(item)}
                      />
                    </TableCell>
                  )}
                  <TableCell>
                    <Link className="text-primary hover:underline" to={`${REQUESTS_BASE}/${item.request_id}`}>
                      {item.sys_number}
                    </Link>
                    {item.in_agreement_on_review && (
                      <Badge variant="outline" className="ml-2">
                        {t('bpp.plan.inAgreement', 'В договоре на согласовании')}
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell>{item.project_code ?? '—'}</TableCell>
                  <TableCell>{item.article_name ?? '—'}</TableCell>
                  <TableCell>{item.name}</TableCell>
                  <TableCell>{item.uom ?? '—'}</TableCell>
                  <TableCell className="text-right">{shownQty(item.qty)}</TableCell>
                  <TableCell className="text-right">{shownQty(item.qty_in_invoices)}</TableCell>
                  <TableCell className="text-right">{shownQty(item.qty_left)}</TableCell>
                  <TableCell className="text-right">{formatMoney(item.amount)}</TableCell>
                  <TableCell className="text-right">{formatMoney(item.amount_left)}</TableCell>
                  <TableCell className={item.overdue ? 'text-destructive' : undefined}>
                    {formatDate(item.need_date)}
                  </TableCell>
                  {readOnly && <TableCell>{item.executor_name ?? '—'}</TableCell>}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <div className="flex items-center justify-between text-sm">
        <span className="text-muted-foreground">
          {t('bpp.registry.totalRows', 'Всего: {{count}}', { count: total })}
        </span>
        <div className="flex items-center gap-2">
          <Select
            value={String(state.pageSize)}
            onValueChange={(value) => state.setPageSize(Number(value) as PageSize)}
          >
            <SelectTrigger className="h-8 w-20" aria-label={t('bpp.registry.pageSize', 'Строк на странице')}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PAGE_SIZES.map((size) => <SelectItem key={size} value={String(size)}>{size}</SelectItem>)}
            </SelectContent>
          </Select>
          <Button
            variant="outline" size="icon" disabled={state.page <= 1}
            aria-label={t('bpp.registry.prev', 'Назад')} onClick={() => state.setPage(state.page - 1)}
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <span>{state.page} / {pageCount}</span>
          <Button
            variant="outline" size="icon" disabled={state.page >= pageCount}
            aria-label={t('bpp.registry.next', 'Вперёд')} onClick={() => state.setPage(state.page + 1)}
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      </div>

      <PlanWizardDialog selection={wizard} onClose={() => setWizard(null)} />
    </div>
  );
}

export default PlanPage;
