/**
 * Реестр «Подотчётные средства» (B4.1, ТЗ §19): номер, подотчётное лицо,
 * проект, статья, цель, сумма, подтверждено отчётами, статус, «Сейчас у».
 * Выборку режет сервер: сотрудник видит свои заявки и ждущие его решения,
 * ФД и бухгалтер — все.
 *
 * «Создать» — СН и ПМ (узел `bpp.accountable` `create`): проект, статья
 * бюджета из групп роли (как у заявки на закупку) с остатком, сумма и цель.
 * Сумма сверх остатка статьи — отказ сервера `E-BUD-01` с остатком в тексте.
 */
import { useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { Loader2, Plus } from 'lucide-react';

import { newIdempotencyKey } from '@/api/files';
import { Button } from '@/components/ui/button';
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { usePermissions } from '@/hooks/usePermissions';
import { reportApiError } from '@/lib/apiError';

import { lessThan } from '../budgets/cents';
import { BppRegistry } from '../core/BppRegistry';
import { currentHoldersColumn, moneyColumn, statusColumn } from '../core/registryColumns';
import type { RegistryColumn, RegistryFilter } from '../core/registryTypes';
import { STATUS_DICTIONARIES } from '../core/statusDictionaries';
import { formatMoney, parseMoneyInput } from '../format';
import { projectApi, projectKeys } from '../projects/api';
import { bppRequestsApi, type InitiatorRole } from '../requests/api';

import {
  ACCOUNTABLE_BASE, ACCOUNTABLE_ENDPOINT, bppAccountableApi, type AccountableRow,
} from './api';
import { MigratedBadge } from '../migration/MigratedBadge';

const GOAL_MAX = 2000;
const ROLE_TITLES: Record<InitiatorRole, string> = { sn: 'Снабженец', pm: 'Руководитель проекта' };

function CreateDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const me = useQuery({ queryKey: ['bpp', 'me'], queryFn: bppRequestsApi.me, staleTime: 60_000, enabled: open });
  const roles = me.data?.initiator_roles ?? [];
  const [role, setRole] = useState<InitiatorRole | ''>('');
  const activeRole = role || roles[0] || '';
  const [projectId, setProjectId] = useState('');
  const [articleId, setArticleId] = useState('');
  const [amount, setAmount] = useState('');
  const [goal, setGoal] = useState('');
  const [pending, setPending] = useState(false);
  const [key, setKey] = useState(newIdempotencyKey);

  const projectList = useQuery({
    queryKey: projectKeys.list('', false),
    queryFn: () => projectApi.list('', false),
    enabled: open,
    staleTime: 5 * 60 * 1000,
  });
  const activeProjects = (projectList.data ?? []).filter((p) => p.status === 'active');
  const lines = useQuery({
    queryKey: ['bpp', 'budget-lines', projectId, activeRole],
    queryFn: () => bppRequestsApi.budgetLines(projectId, activeRole as InitiatorRole),
    enabled: open && Boolean(projectId) && Boolean(activeRole),
  });
  const line = lines.data?.find((row) => row.article_id === articleId);
  const parsed = parseMoneyInput(amount);
  const overLine = Boolean(line && parsed !== null && lessThan(line.available, parsed));
  const ready = Boolean(projectId && articleId && goal.trim() && parsed !== null
    && lessThan('0', parsed) && !overLine);

  const create = async () => {
    if (!ready || pending) return;
    setPending(true);
    try {
      const card = await bppAccountableApi.create(key, {
        project_id: projectId, article_id: articleId, amount: parsed!, goal: goal.trim(),
      });
      void queryClient.invalidateQueries({ queryKey: ['bpp', 'registry', 'accountable'] });
      onClose();
      navigate(`${ACCOUNTABLE_BASE}/${card.id}`);
    } catch (error) {
      reportApiError(error, t('bpp.accountable.createFailed', 'Не удалось создать заявку на подотчёт'));
      // Сервер ответил по существу — следующая попытка уже новое действие.
      setKey(newIdempotencyKey());
    } finally {
      setPending(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(next) => { if (!next && !pending) onClose(); }}>
      <DialogContent aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>{t('bpp.accountable.createTitle', 'Заявка на подотчётные средства')}</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          {roles.length > 1 && (
            <div className="space-y-1.5">
              <Label htmlFor="acc-role">{t('bpp.requests.role', 'Роль')}</Label>
              <Select value={activeRole} onValueChange={(value) => {
                setRole(value as InitiatorRole);
                setArticleId('');
              }}>
                <SelectTrigger id="acc-role"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {roles.map((value) => <SelectItem key={value} value={value}>{ROLE_TITLES[value]}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
          )}
          <div className="space-y-1.5">
            <Label htmlFor="acc-project">{t('bpp.requests.project', 'Проект')}</Label>
            <Select value={projectId || undefined} onValueChange={(value) => {
              setProjectId(value);
              setArticleId('');
            }}>
              <SelectTrigger id="acc-project">
                <SelectValue placeholder={t('bpp.requests.pickProject', 'Выберите проект')} />
              </SelectTrigger>
              <SelectContent>
                {activeProjects.map((p) => (
                  <SelectItem key={p.id} value={p.id}>{`${p.code} — ${p.name}`}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            {projectList.data && activeProjects.length === 0 && (
              <p className="text-xs text-muted-foreground">
                {t('bpp.accountable.noProjects', 'Нет действующих проектов, в которых вы участвуете.')}
              </p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="acc-article">{t('bpp.requests.article', 'Статья бюджета')}</Label>
            <Select value={articleId || undefined} disabled={!projectId} onValueChange={setArticleId}>
              <SelectTrigger id="acc-article">
                <SelectValue placeholder={projectId
                  ? t('bpp.requests.pickArticle', 'Выберите статью')
                  : t('bpp.requests.projectFirst', 'Сначала выберите проект')} />
              </SelectTrigger>
              <SelectContent>
                {(lines.data ?? []).map((row) => (
                  <SelectItem key={row.article_id} value={row.article_id}>
                    {`${row.article_code} — ${row.article_name}`}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {projectId && lines.data && lines.data.length === 0 && (
              <p className="text-xs text-muted-foreground">
                {t('bpp.requests.noLines',
                  'По проекту нет утверждённых лимитов по вашим статьям. Обратитесь к финансовому директору.')}
              </p>
            )}
            {line && (
              <p className="text-xs text-muted-foreground">
                {t('bpp.accountable.available', 'Доступный остаток статьи')}: {formatMoney(line.available)}
              </p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="acc-amount">{t('bpp.accountable.amount', 'Сумма')}</Label>
            <Input id="acc-amount" className="text-right" inputMode="decimal" value={amount}
              onChange={(event) => setAmount(event.target.value)}
              onBlur={() => { if (parsed !== null) setAmount(formatMoney(parsed)); }} />
            {amount && parsed === null && (
              <p className="text-xs text-destructive">{t('bpp.format.money', 'Введите сумму в формате 1 250 000,00')}</p>
            )}
            {overLine && line && (
              <p role="alert" className="text-xs text-destructive">
                {t('bpp.accountable.overLine', 'Сумма больше доступного остатка статьи ({{sum}})', {
                  sum: formatMoney(line.available),
                })}
              </p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="acc-goal">{t('bpp.accountable.goal', 'Цель')}</Label>
            <Textarea id="acc-goal" rows={3} maxLength={GOAL_MAX} value={goal}
              onChange={(event) => setGoal(event.target.value)} />
          </div>
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" disabled={pending} onClick={onClose}>
            {t('bpp.document.cancel', 'Отмена')}
          </Button>
          <Button type="button" disabled={!ready || pending} onClick={() => void create()}>
            {pending && <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />}
            {t('bpp.accountable.create', 'Создать')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function AccountablePage() {
  const { t } = useTranslation();
  const permissions = usePermissions();
  const canCreate = permissions.can('bpp.accountable', 'create');
  const [creating, setCreating] = useState(false);
  const projects = useQuery({
    queryKey: projectKeys.list('', false),
    queryFn: () => projectApi.list('', false),
    staleTime: 5 * 60 * 1000,
  });

  const columns = useMemo<RegistryColumn<AccountableRow>[]>(() => [
    {
      key: 'number',
      title: t('bpp.accountable.number', 'Номер'),
      required: true,
      render: (row) => <span>{row.number}<MigratedBadge migrated={row.is_migrated} /></span>,
    },
    { key: 'accountable_user_name', title: t('bpp.accountable.person', 'Подотчётное лицо') },
    { key: 'project_code', title: t('bpp.accountable.project', 'Проект') },
    { key: 'article_name', title: t('bpp.accountable.article', 'Статья') },
    {
      key: 'goal',
      title: t('bpp.accountable.goal', 'Цель'),
      render: (row) => <span className="line-clamp-2 max-w-xs">{row.goal}</span>,
    },
    moneyColumn<AccountableRow>('amount', t('bpp.accountable.amount', 'Сумма'),
      { currency: 'currency', totalKey: 'amount' }),
    moneyColumn<AccountableRow>('reported_amount', t('bpp.accountable.reported', 'Подтверждено отчётами'),
      { currency: 'currency' }),
    statusColumn<AccountableRow>(t, 'accountable'),
    currentHoldersColumn<AccountableRow>(t),
  ], [t]);

  const filters = useMemo<RegistryFilter[]>(() => [
    {
      key: 'status',
      label: t('bpp.registry.status', 'Статус'),
      kind: 'select',
      options: Object.entries(STATUS_DICTIONARIES.accountable).map(([value, entry]) => ({
        value, label: t(entry.labelKey, entry.label),
      })),
    },
    {
      key: 'project_id',
      label: t('bpp.accountable.project', 'Проект'),
      kind: 'select',
      options: (projects.data ?? []).map((project) => ({
        value: project.id, label: `${project.code} — ${project.name}`,
      })),
    },
    {
      key: 'awaiting_me',
      label: t('bpp.requests.awaitingMe', 'Ждёт моего решения'),
      kind: 'select',
      options: [{ value: '1', label: t('bpp.common.yes', 'Да') }],
    },
    { key: 'date_from', label: t('bpp.accountable.dateFrom', 'Создана с'), kind: 'date' },
    { key: 'date_to', label: t('bpp.accountable.dateTo', 'Создана по'), kind: 'date' },
  ], [projects.data, t]);

  return (
    <div className="space-y-4">
      <h2 className="text-2xl font-bold tracking-tight">
        {t('bpp.accountable.registryTitle', 'Подотчётные средства')}
      </h2>
      <BppRegistry<AccountableRow>
        registryKey="accountable"
        endpoint={ACCOUNTABLE_ENDPOINT}
        columns={columns}
        filters={filters}
        exportName="accountable"
        searchParam="search"
        searchPlaceholder={t('bpp.accountable.search', 'Номер или цель')}
        defaultHidden={['current_holders']}
        rowHref={(row) => `${ACCOUNTABLE_BASE}/${row.id}`}
        rowLabel={(row) => row.number}
        toolbarExtra={canCreate ? (
          <Button size="sm" onClick={() => setCreating(true)}>
            <Plus className="mr-1.5 h-4 w-4" />
            {t('bpp.accountable.create', 'Создать')}
          </Button>
        ) : undefined}
      />
      {creating && <CreateDialog open={creating} onClose={() => setCreating(false)} />}
    </div>
  );
}

export default AccountablePage;
