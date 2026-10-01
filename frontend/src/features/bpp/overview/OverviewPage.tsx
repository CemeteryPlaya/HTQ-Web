/**
 * «Обзор» модуля (ТЗ §05, §17; решение пользователя 01.10) — стартовая
 * страница раздела «Закупки и оплаты» по ролям: как «Обзор» старых
 * «Договоров», но что показать и какие числа — решает сервер по правам
 * пользователя (`GET /api/bpp/v1/overview`, `services/overview.py`).
 *
 * - Карточка — только у пришедшего блока: нет права или подмодуль выключен
 *   у компании — нет и карточки (а не «0»). Раздел без карточек не рисуется.
 * - Сверху — «Ждут моего решения» и главная очередь роли: «На решение ФД» у
 *   ФД, «К оплате» у БУХ, «Нет исполнителя» у АДМ, «Ждут закрывающих» у
 *   авторов счетов, черновики заявок у остальных инициаторов.
 * - Бюджеты — каждый проект отдельно (решение Руслана 01.10): таблица
 *   «Лимит / Задействовано / Доступно» по проектам в карточке «Бюджеты»,
 *   строка — ссылка на карточку бюджета. Общей суммы по проектам нет —
 *   деньги одного проекта другому не отдать.
 * - Ссылка у числа — только туда, где его можно пересчитать: очереди счетов
 *   ведут на вкладку реестра (`?tab=`), и число совпадает с её `total`. Чипы
 *   статусов заявок, договоров и подотчёта — без ссылки (эти реестры по
 *   адресу не фильтруются, и ссылка показала бы весь список под чужим
 *   числом); нулевой статус не показывается, нулевая очередь — показывается.
 * - «Создать» — где у раздела есть страница создания (бюджет, заявка) и
 *   сервер разрешил (`can_create`); договор и счёт оформляются из Плана
 *   закупок, подотчёт — диалогом своего реестра.
 * - Деньги — только `formatMoney` над строкой сервера; у АДМ денег нет
 *   (`shows_money: false`) — у бюджетов одни количества.
 * - Свежие числа при каждом открытии (`staleTime: 0`, `refetchOnMount:
 *   'always'`).
 */
import { useState, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import type { TFunction } from 'i18next';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import {
  AlertTriangle, BarChart3, BookMarked, ClipboardList, FileSignature, FolderKanban, GitBranch,
  Landmark, LayoutDashboard, ListChecks, Plus, Receipt, Scale, Settings, Stamp, Wallet,
  type LucideIcon,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { cn } from '@/lib/utils';

import { formatMoney } from '../format';

import {
  budgetHref, invoiceTabHref, OVERVIEW_LINKS as LINKS, overviewApi, overviewKeys,
  type BudgetProjectMoney, type InvoiceTab, type Overview, type OverviewAdmin,
} from './api';

const KZT = 'KZT';
/** Сколько проектов в таблице бюджетов до «Показать все». */
const BUDGET_ROWS = 10;

/** Вкладки счетов в порядке реестра L-06 и их подписи там же. */
const INVOICE_TABS: [InvoiceTab, string, string][] = [
  ['fd', 'bpp.overview.tab.fd', 'На решение ФД'],
  ['to_pay', 'bpp.overview.tab.toPay', 'К оплате'],
  ['awaiting_docs', 'bpp.overview.tab.awaitingDocs', 'Ждут закрывающих'],
  ['docs_provided', 'bpp.overview.tab.docsProvided', 'Документы предоставлены'],
  ['bank_unconfirmed', 'bpp.overview.tab.bankUnconfirmed', 'Оплачено, банк не подтвердил'],
];

interface Stat {
  key: string;
  icon: LucideIcon;
  label: string;
  value: ReactNode;
  hint?: string;
  to?: string;
}

function StatCard({ stat }: { stat: Stat }) {
  const Icon = stat.icon;
  const body = (
    <Card className={cn('h-full', stat.to && 'transition-colors hover:border-primary')}>
      <CardHeader className="pb-3">
        <CardDescription className="flex items-center gap-2">
          <Icon className="h-4 w-4" />
          {stat.label}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <p className="text-3xl font-bold tabular-nums">{stat.value}</p>
        {stat.hint && <p className="mt-1 text-xs text-muted-foreground">{stat.hint}</p>}
      </CardContent>
    </Card>
  );
  if (!stat.to) return <div data-stat={stat.key}>{body}</div>;
  return (
    <Link to={stat.to} data-stat={stat.key}
      className="block rounded-lg focus:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      {body}
    </Link>
  );
}

/** Главная очередь роли: у нескольких ролей — первая по этому порядку. */
function queueStat(data: Overview, t: TFunction): Stat | null {
  const tabs = data.invoices?.tabs ?? {};
  const tab = (key: InvoiceTab, label: string): Stat => ({
    key, icon: Receipt, label, value: tabs[key] ?? 0, to: invoiceTabHref(key),
  });
  if (tabs.fd !== undefined) return tab('fd', t('bpp.overview.queue.fd', 'Счета на решение ФД'));
  if (tabs.to_pay !== undefined) return tab('to_pay', t('bpp.overview.queue.toPay', 'Счета к оплате'));
  if (data.admin) {
    return {
      key: 'no_executor', icon: AlertTriangle, value: data.admin.no_executor,
      label: t('bpp.overview.noExecutor', 'Нет исполнителя'),
      hint: t('bpp.overview.noExecutorHint', 'документы ждут исполнителя этапа согласования'),
    };
  }
  if (tabs.awaiting_docs !== undefined) {
    return tab('awaiting_docs', t('bpp.overview.queue.awaitingDocs', 'Ждут закрывающих документов'));
  }
  if (data.requests?.can_create) {
    return {
      key: 'drafts', icon: ClipboardList, value: data.requests.draft, to: LINKS.requests,
      label: t('bpp.overview.queue.drafts', 'Черновики заявок'),
    };
  }
  return null;
}

interface Chip {
  key: string;
  label: string;
  value: number;
  /** Есть ссылка — очередь (видна и с нулём); нет — статус (нуль скрыт). */
  href?: string;
}

function ChipRow({ chips }: { chips: Chip[] }) {
  const shown = chips.filter((chip) => chip.href || chip.value > 0);
  if (!shown.length) return null;
  const base = 'inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs';
  return (
    <ul className="flex flex-wrap gap-1.5">
      {shown.map((chip) => {
        const body = (
          <>
            <span className="text-muted-foreground">{chip.label}</span>
            <span className="font-semibold tabular-nums">{chip.value}</span>
          </>
        );
        return (
          <li key={chip.key} data-chip={chip.key}>
            {chip.href ? (
              <Link to={chip.href}
                className={cn(base, 'transition-colors hover:border-primary hover:text-primary')}>
                {body}
              </Link>
            ) : (
              <span className={base}>{body}</span>
            )}
          </li>
        );
      })}
    </ul>
  );
}

interface ModuleCardProps {
  block: string;
  icon: LucideIcon;
  title: string;
  description: string;
  to: string;
  /** Нет — карточка-ссылка без числа (выписки, дашборд). */
  total?: number;
  totalLabel?: string;
  chips?: Chip[];
  create?: { to: string; label: string } | null;
  children?: ReactNode;
  /** На всю ширину раздела — под таблицу (бюджеты по проектам). */
  wide?: boolean;
}

function ModuleCard({
  block, icon: Icon, title, description, to, total, totalLabel, chips = [], create, children, wide,
}: ModuleCardProps) {
  const { t } = useTranslation();
  return (
    <Card className={cn('flex flex-col', wide && 'md:col-span-2 xl:col-span-3')} data-block={block}>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Icon className="h-5 w-5 text-muted-foreground" />
          {title}
        </CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="mt-auto space-y-3">
        {total !== undefined && (
          <div>
            <p className="text-xs text-muted-foreground">{totalLabel ?? t('bpp.overview.total', 'Всего')}</p>
            <p className="mt-1 text-2xl font-semibold tabular-nums" data-total>{total}</p>
          </div>
        )}
        <ChipRow chips={chips} />
        {children}
        <div className="flex flex-wrap gap-2 pt-1">
          <Button asChild size="sm" variant="outline">
            <Link to={to}>{t('bpp.overview.open', 'Открыть')}</Link>
          </Button>
          {create && (
            <Button asChild size="sm">
              <Link to={create.to}>
                <Plus className="mr-1.5 h-3.5 w-3.5" />
                {create.label}
              </Link>
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

/** Бюджет каждого проекта отдельно: лимит, задействовано, доступно — в
 * валюте бюджета; строка ведёт в карточку бюджета. Первые `BUDGET_ROWS`,
 * остальные — по «Показать все». */
function BudgetProjects({ rows }: { rows: BudgetProjectMoney[] }) {
  const { t } = useTranslation();
  const [all, setAll] = useState(false);
  if (!rows.length) {
    return (
      <p className="text-sm text-muted-foreground">
        {t('bpp.overview.budgets.none', 'Утверждённых бюджетов по вашим статьям пока нет')}
      </p>
    );
  }
  const shown = all ? rows : rows.slice(0, BUDGET_ROWS);
  const money = 'text-right tabular-nums whitespace-nowrap';
  return (
    <div className="space-y-1">
      <Table data-testid="budget-projects">
        <TableHeader>
          <TableRow>
            <TableHead>{t('bpp.overview.budgets.project', 'Проект')}</TableHead>
            <TableHead className="text-right">{t('bpp.overview.budgets.limit', 'Лимит')}</TableHead>
            <TableHead className="text-right">
              {t('bpp.overview.budgets.committed', 'Задействовано')}
            </TableHead>
            <TableHead className="text-right">{t('bpp.overview.budgets.available', 'Доступно')}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {shown.map((row) => (
            <TableRow key={row.budget_id} data-project={row.project.code ?? ''}>
              <TableCell>
                <Link to={budgetHref(row.budget_id)} className="hover:underline">
                  {row.project.code && (
                    <span className="mr-2 font-mono text-xs text-muted-foreground">{row.project.code}</span>
                  )}
                  {row.project.name ?? '—'}
                </Link>
              </TableCell>
              <TableCell className={money}>{formatMoney(row.limit_amount, row.currency_code)}</TableCell>
              <TableCell className={money}>{formatMoney(row.committed, row.currency_code)}</TableCell>
              <TableCell className={cn(money, 'font-medium',
                row.available.trim().startsWith('-') && 'text-destructive')}>
                {formatMoney(row.available, row.currency_code)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {rows.length > BUDGET_ROWS && (
        <Button variant="link" size="sm" className="px-0" onClick={() => setAll((value) => !value)}>
          {all
            ? t('bpp.overview.budgets.fewer', 'Свернуть')
            : t('bpp.overview.budgets.all', 'Показать все ({{n}})', { n: rows.length })}
        </Button>
      )}
    </div>
  );
}

interface AdminLink {
  key: string;
  to: string;
  icon: LucideIcon;
  label: string;
}

function AdminCard({ admin }: { admin: OverviewAdmin }) {
  const { t } = useTranslation();
  const candidates: (AdminLink | false)[] = [
    admin.routes && { key: 'routes', to: LINKS.routes, icon: GitBranch, label: t('bpp.routes.title', 'Маршруты согласования') },
    admin.settings && { key: 'settings', to: LINKS.settings, icon: Settings, label: t('bpp.bankSettings.title', 'Настройки') },
    admin.refdata && { key: 'refdata', to: LINKS.refdata, icon: BookMarked, label: t('bpp.refdata.title', 'Справочники') },
    admin.projects && { key: 'projects', to: LINKS.projects, icon: FolderKanban, label: t('bpp.projects.title', 'Проекты') },
  ];
  const links = candidates.filter((link): link is AdminLink => Boolean(link));
  return (
    <Card data-block="admin" className="md:col-span-2 xl:col-span-3">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Settings className="h-5 w-5 text-muted-foreground" />
          {t('bpp.overview.admin.title', 'Администрирование модуля')}
        </CardTitle>
        <CardDescription>
          {t('bpp.overview.admin.description',
            'Маршруты, справочники и настройки компании; документы, которым нужен исполнитель этапа.')}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div>
          <p className="text-xs text-muted-foreground">
            {t('bpp.overview.admin.noExecutor', 'Документы без исполнителя этапа')}
          </p>
          <p className={cn('mt-1 text-2xl font-semibold tabular-nums', admin.no_executor > 0 && 'text-destructive')}
            data-total>
            {admin.no_executor}
          </p>
          {admin.no_executor > 0 && (
            <p className="text-xs text-muted-foreground">
              {t('bpp.overview.admin.noExecutorHint',
                'Назначьте держателя или временного исполнителя должности — документ продолжит путь сам.')}
            </p>
          )}
        </div>
        {links.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {links.map((link) => {
              const Icon = link.icon;
              return (
                <Button key={link.key} asChild size="sm" variant="outline">
                  <Link to={link.to}>
                    <Icon className="mr-1.5 h-3.5 w-3.5" />
                    {link.label}
                  </Link>
                </Button>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Section({ id, title, description, cards }: {
  id: string;
  title: string;
  description: string;
  cards: ReactNode[];
}) {
  const present = cards.filter(Boolean);
  if (!present.length) return null;
  return (
    <section data-section={id} aria-labelledby={`bpp-overview-${id}`} className="space-y-4">
      <div>
        <h3 id={`bpp-overview-${id}`} className="text-lg font-semibold">{title}</h3>
        <p className="text-sm text-muted-foreground">{description}</p>
      </div>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{present}</div>
    </section>
  );
}

export function OverviewPage() {
  const { t } = useTranslation();
  const query = useQuery({
    queryKey: overviewKeys.all,
    queryFn: overviewApi.get,
    staleTime: 0,
    refetchOnMount: 'always',
  });

  const header = (
    <div>
      <h2 className="text-2xl font-bold">{t('bpp.overview.title', 'Обзор')}</h2>
      <p className="text-sm text-muted-foreground">
        {t('bpp.overview.subtitle', 'Очереди и документы, открытые вашей роли')}
      </p>
    </div>
  );

  if (query.isLoading) {
    return (
      <section className="space-y-6">
        {header}
        <div className="grid gap-4 sm:grid-cols-3">
          {[0, 1, 2].map((key) => <Skeleton key={key} className="h-28 w-full" />)}
        </div>
        <Skeleton className="h-64 w-full" />
      </section>
    );
  }
  if (query.isError || !query.data) {
    return (
      <section className="space-y-6">
        {header}
        <div role="alert" className="rounded-lg border bg-card p-6">
          <p className="text-sm text-destructive">
            {t('bpp.overview.loadError', 'Не удалось загрузить обзор')}
          </p>
          <Button size="sm" variant="outline" className="mt-3" onClick={() => void query.refetch()}>
            {t('bpp.overview.retry', 'Повторить')}
          </Button>
        </div>
      </section>
    );
  }

  const data = query.data;
  const { budgets, requests, plan, agreements, invoices, accountable, alternatives, kpi, admin } = data;
  const create = t('bpp.overview.create', 'Создать');
  const drafts = t('bpp.overview.drafts', 'Черновики');
  const onReview = t('bpp.overview.inApproval', 'На согласовании');
  const rework = t('bpp.overview.rework', 'На доработке');

  const stats = [
    data.approvals ? {
      key: 'approvals', icon: Stamp, value: data.approvals.pending, to: LINKS.approvals,
      label: t('bpp.overview.approvals', 'Ждут моего решения'),
    } : null,
    queueStat(data, t),
  ].filter((stat): stat is Stat => stat !== null);

  const procurement = [
    budgets && (
      <ModuleCard key="budgets" block="budgets" icon={Wallet} to={LINKS.budgets}
        wide={budgets.projects !== undefined}
        title={t('bpp.budgets.title', 'Бюджеты')}
        description={t('bpp.overview.budgets.description',
          'Бюджет каждого проекта отдельно: лимит, задействовано и доступно по статьям.')}
        total={budgets.total}
        chips={[
          { key: 'approved', label: t('bpp.overview.approved', 'Утверждены'), value: budgets.approved },
          { key: 'draft', label: drafts, value: budgets.draft },
        ]}
        create={budgets.can_create ? { to: LINKS.budgetNew, label: create } : null}>
        {budgets.projects && <BudgetProjects rows={budgets.projects} />}
      </ModuleCard>
    ),
    requests && (
      <ModuleCard key="requests" block="requests" icon={ClipboardList} to={LINKS.requests}
        title={t('bpp.requests.title', 'Заявки на закупку')}
        description={t('bpp.overview.requests.description', 'Потребность проектов и её согласование.')}
        total={requests.total}
        chips={[
          { key: 'draft', label: drafts, value: requests.draft },
          { key: 'in_approval', label: onReview, value: requests.in_approval },
          { key: 'rework', label: rework, value: requests.rework },
          { key: 'approved', label: t('bpp.overview.approved', 'Утверждены'), value: requests.approved },
        ]}
        create={requests.can_create ? { to: LINKS.requestNew, label: create } : null} />
    ),
    plan && (
      <ModuleCard key="plan" block="plan" icon={ListChecks} to={LINKS.plan}
        title={t('bpp.plan.title', 'План закупок')}
        description={t('bpp.overview.plan.description',
          'Позиции утверждённых заявок, по которым оформляют договор или счёт.')}
        total={plan.open} totalLabel={t('bpp.overview.plan.open', 'Открытых позиций')} />
    ),
  ];

  const payments = [
    agreements && (
      <ModuleCard key="agreements" block="agreements" icon={FileSignature} to={LINKS.agreements}
        title={t('bpp.agreements.title', 'Договоры')}
        description={t('bpp.overview.agreements.description', 'Договоры с поставщиками: согласование и исполнение.')}
        total={agreements.total}
        chips={[
          { key: 'on_review', label: onReview, value: agreements.on_review },
          { key: 'rework', label: rework, value: agreements.rework },
          { key: 'active', label: t('bpp.overview.active', 'Действуют'), value: agreements.active },
          { key: 'draft', label: drafts, value: agreements.draft },
        ]} />
    ),
    invoices && (
      <ModuleCard key="invoices" block="invoices" icon={Receipt} to={LINKS.invoices}
        title={t('bpp.invoices.title', 'Счета на оплату')}
        description={t('bpp.overview.invoices.description',
          'Решение ФД, оплата бухгалтерией и закрывающие документы.')}
        total={invoices.total}
        chips={[
          ...INVOICE_TABS
            .filter(([tab]) => invoices.tabs[tab] !== undefined)
            .map(([tab, key, fallback]) => ({
              key: tab, label: t(key, fallback), value: invoices.tabs[tab] ?? 0, href: invoiceTabHref(tab),
            })),
          { key: 'draft', label: drafts, value: invoices.draft },
          { key: 'returned', label: t('bpp.overview.returned', 'Возвращены на доработку'), value: invoices.returned },
        ]} />
    ),
    accountable && (
      <ModuleCard key="accountable" block="accountable" icon={Wallet} to={LINKS.accountable}
        title={t('bpp.accountable.registryTitle', 'Подотчёт')}
        description={t('bpp.overview.accountable.description',
          'Подотчётные средства и авансовые отчёты по ним.')}
        total={accountable.total}
        chips={[
          ...(accountable.awaiting_accounting !== undefined ? [{
            key: 'awaiting_accounting', value: accountable.awaiting_accounting,
            label: t('bpp.overview.awaitingAccounting', 'Ожидают выдачи бухгалтерией'),
          }] : []),
          {
            key: 'awaiting_report', value: accountable.awaiting_report,
            label: t('bpp.overview.awaitingReport', 'Ожидают авансовый отчёт'),
          },
        ]} />
    ),
    data.bank && (
      <ModuleCard key="bank" block="bank" icon={Landmark} to={LINKS.bank}
        title={t('bpp.bank.title', 'Оплаты факт')}
        description={t('bpp.overview.bank.description', 'Выписки банка и их сверка со счетами.')} />
    ),
    data.dashboard && (
      <ModuleCard key="dashboard" block="dashboard" icon={LayoutDashboard} to={LINKS.dashboard}
        title={t('bpp.dashboard.title', 'Дашборд оплат')}
        description={t('bpp.overview.dashboard.description',
          'Очереди счетов, оплаты по статьям и неделям, крупнейшие контрагенты.')} />
    ),
  ];

  const choice = [
    alternatives && (
      <ModuleCard key="alternatives" block="alternatives" icon={Scale} to={LINKS.alternatives}
        title={t('bpp.alternatives.menu', 'Альтернативы')}
        description={t('bpp.overview.alternatives.description',
          'Альтернативные предложения поставщиков по счетам и договорам.')}
        total={alternatives.feed} totalLabel={t('bpp.overview.alternatives.feed', 'Открыты для альтернатив')}
        chips={[
          ...(alternatives.submitted !== undefined ? [{
            key: 'submitted', value: alternatives.submitted,
            label: t('bpp.overview.alternatives.submitted', 'Ждут решения'),
          }] : []),
          ...(alternatives.mine_submitted !== undefined ? [{
            key: 'mine_submitted', value: alternatives.mine_submitted,
            label: t('bpp.overview.alternatives.mine', 'Мои поданные'),
          }] : []),
        ]} />
    ),
    kpi && (
      <ModuleCard key="kpi" block="kpi" icon={BarChart3} to={LINKS.kpi}
        title={t('bpp.overview.kpi.title', 'KPI снабжения')}
        description={t('bpp.overview.kpi.description', 'Экономия от выбранных альтернатив.')}
        total={kpi.preliminary + kpi.confirmed} totalLabel={t('bpp.overview.kpi.total', 'Записей KPI')}
        chips={[
          { key: 'preliminary', label: t('bpp.overview.kpi.preliminary', 'Предварительные'), value: kpi.preliminary },
          { key: 'confirmed', label: t('bpp.overview.kpi.confirmed', 'Подтверждённые'), value: kpi.confirmed },
        ]}>
        {kpi.saving_confirmed !== undefined && (
          <p className="text-sm" data-money="saving">
            <span className="text-muted-foreground">
              {t('bpp.overview.kpi.saving', 'Подтверждённая экономия')}:
            </span>{' '}
            <span className="font-medium tabular-nums">{formatMoney(kpi.saving_confirmed, KZT)}</span>
          </p>
        )}
      </ModuleCard>
    ),
  ];

  return (
    <section className="space-y-8">
      {header}
      {stats.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {stats.map((stat) => <StatCard key={stat.key} stat={stat} />)}
        </div>
      )}
      <Section id="procurement" cards={procurement}
        title={t('bpp.overview.section.procurement', 'Бюджет и закупки')}
        description={t('bpp.overview.section.procurementHint',
          'Деньги проектов и потребность: бюджеты, заявки, план закупок.')} />
      <Section id="payments" cards={payments}
        title={t('bpp.overview.section.payments', 'Договоры и оплаты')}
        description={t('bpp.overview.section.paymentsHint',
          'Оформление и оплата: договоры, счета, подотчёт, выписки банка.')} />
      <Section id="choice" cards={choice}
        title={t('bpp.overview.section.choice', 'Альтернативы и KPI')}
        description={t('bpp.overview.section.choiceHint',
          'Альтернативные предложения поставщиков и экономия по ним.')} />
      <Section id="admin" cards={[admin && <AdminCard key="admin" admin={admin} />]}
        title={t('bpp.overview.section.admin', 'Администрирование')}
        description={t('bpp.overview.section.adminHint', 'Настройка модуля под компанию.')} />
    </section>
  );
}

export default OverviewPage;
