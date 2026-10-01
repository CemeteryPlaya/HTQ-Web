/**
 * Лента L-09 «Закупки для альтернатив» (ТЗ §12.2): счета без договора «На
 * рассмотрении ФД» и договоры «На согласовании», которым можно предложить
 * альтернативу. Новые отправки сверху; фильтры — вид, проект, статья, сумма,
 * период отправки, «без альтернатив», «только мои»; быстрый поиск — по
 * наименованию позиций.
 *
 * - Ссылка уведомления `?source=<invoice|agreement>:<id>` сужает ленту до
 *   одного документа; над таблицей — плашка с «Показать всю ленту».
 * - «Предложить альтернативу» заводит черновик и открывает форму F-07; там,
 *   где у человека уже есть своя АП, вместо кнопки — ссылка «Моя
 *   альтернатива». Лимиты и окно подачи проверяет сервер (отказ — тостом).
 * - Строка ведёт на исходный документ; фильтры и страницы считает сервер.
 */
import { useCallback, useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { ChevronDown, Loader2, X } from 'lucide-react';

import { newIdempotencyKey } from '@/api/files';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu, DropdownMenuCheckboxItem, DropdownMenuContent, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { usePermissions } from '@/hooks/usePermissions';
import { reportApiError } from '@/lib/apiError';

import type { CounterpartyBrief } from '../agreements/api';
import { CounterpartyPicker } from '../agreements/CounterpartyPicker';
import { BppRegistry } from '../core/BppRegistry';
import { moneyColumn } from '../core/registryColumns';
import type { RegistryColumn, RegistryFilter } from '../core/registryTypes';
import { StatusBadge } from '../core/StatusBadge';
import { formatDateTime } from '../format';
import { projectApi, projectKeys } from '../projects/api';
import { refdataApi, refdataKeys } from '../refdata/api';

import {
  FEED_PAGE_FILTERS, alternativesApi, feedEndpoint, feedRows, offerHref, parseSource, type FeedRow,
} from './api';

function ProposeButton({ row }: { row: FeedRow }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [pending, setPending] = useState(false);

  const propose = async () => {
    setPending(true);
    try {
      const created = await alternativesApi.create(newIdempotencyKey(), row.source_type, row.source_id);
      void queryClient.invalidateQueries({ queryKey: ['bpp', 'registry', 'alternatives'] });
      navigate(offerHref(created.id));
    } catch (error) {
      reportApiError(error, t('bpp.alternatives.createFailed', 'Не удалось начать альтернативу'));
    } finally {
      setPending(false);
    }
  };

  return (
    <Button type="button" size="sm" variant="outline" disabled={pending} onClick={propose}>
      {pending && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
      {t('bpp.alternatives.propose', 'Предложить альтернативу')}
    </Button>
  );
}

/** Множественный выбор (проект, статья): повторяемый параметр адреса. */
function MultiFilter({ label, options, selected, onChange }: {
  label: string;
  options: { value: string; label: string }[];
  selected: string[];
  onChange: (next: string[]) => void;
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button type="button" variant="outline" size="sm" aria-label={label}>
          {label}{selected.length > 0 ? `: ${selected.length}` : ''}
          <ChevronDown className="ml-1.5 h-3.5 w-3.5" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="max-h-72 overflow-auto">
        {options.map((option) => (
          <DropdownMenuCheckboxItem
            key={option.value}
            checked={selected.includes(option.value)}
            onSelect={(event) => event.preventDefault()}
            onCheckedChange={(checked) => onChange(checked
              ? [...selected, option.value]
              : selected.filter((value) => value !== option.value))}
          >
            {option.label}
          </DropdownMenuCheckboxItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function AlternativesFeedPage() {
  const { t } = useTranslation();
  const permissions = usePermissions();
  const [searchParams, setSearchParams] = useSearchParams();
  const source = parseSource(searchParams.get('source')) ? searchParams.get('source') : null;
  const canPropose = permissions.can('bpp.alternatives', 'create');

  // Фильтры страницы живут в адресе и уходят в запрос строкой (повторяемые
  // project_id/article_id — как ждёт сервер); страница сбрасывается.
  const pageFilters = useMemo(() => {
    const out = new URLSearchParams();
    for (const key of FEED_PAGE_FILTERS) {
      for (const value of searchParams.getAll(key)) if (value) out.append(key, value);
    }
    return out;
  }, [searchParams]);
  const pageFiltersKey = pageFilters.toString();
  const setFilter = useCallback((key: (typeof FEED_PAGE_FILTERS)[number], values: string[]) => {
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.delete(key);
      values.forEach((value) => next.append(key, value));
      next.delete('page');
      return next;
    }, { replace: true });
  }, [setSearchParams]);
  const [counterparty, setCounterparty] = useState<CounterpartyBrief | null>(null);
  // Авторы — из строк ленты (отдельной ручки нет); накапливаются, чтобы выбранный не пропал.
  const [authors, setAuthors] = useState<Record<string, string>>({});
  const mapRows = useCallback((raw: unknown[]) => {
    const rows = feedRows(raw);
    setAuthors((current) => {
      const next = { ...current };
      for (const row of rows) if (row.author_id !== null) next[String(row.author_id)] = row.author_name ?? String(row.author_id);
      return Object.keys(next).length === Object.keys(current).length ? current : next;
    });
    return rows;
  }, []);

  const projects = useQuery({
    queryKey: projectKeys.list('', false),
    queryFn: () => projectApi.list('', false),
    staleTime: 5 * 60 * 1000,
  });
  const articles = useQuery({
    queryKey: refdataKeys.list('articles', { active: true }),
    queryFn: () => refdataApi.articles.list({ active: true }),
    staleTime: 5 * 60 * 1000,
  });

  const columns = useMemo<RegistryColumn<FeedRow>[]>(() => [
    {
      key: 'number',
      title: t('bpp.alternatives.feed.document', 'Документ'),
      required: true,
      render: (row) => (
        <span>
          <span className="font-medium">{row.number}</span>
          <span className="block text-xs text-muted-foreground">{row.kind_label}</span>
        </span>
      ),
    },
    {
      key: 'positions',
      title: t('bpp.alternatives.feed.positions', 'Позиции'),
      render: (row) => (
        <span className="text-sm">
          {row.positions.names.join('; ') || '—'}
          {row.positions.more > 0 && (
            <span className="text-muted-foreground">
              {' '}{t('bpp.alternatives.feed.more', 'и ещё {{n}}', { n: row.positions.more })}
            </span>
          )}
        </span>
      ),
    },
    {
      key: 'counterparty',
      title: t('bpp.alternatives.feed.counterparty', 'Контрагент'),
      render: (row) => row.counterparty?.name ?? '—',
    },
    moneyColumn<FeedRow>('amount', t('bpp.alternatives.feed.amount', 'Сумма'),
      { currency: 'currency_code' }),
    {
      key: 'project',
      title: t('bpp.alternatives.feed.project', 'Проект'),
      render: (row) => row.project.code ?? '—',
    },
    {
      key: 'article',
      title: t('bpp.alternatives.feed.article', 'Статья'),
      render: (row) => row.article.name ?? '—',
    },
    {
      key: 'author_name',
      title: t('bpp.alternatives.feed.author', 'Автор'),
      render: (row) => row.author_name ?? '—',
    },
    {
      key: 'sent_at',
      title: t('bpp.alternatives.feed.sentAt', 'Отправлено'),
      render: (row) => (row.sent_at ? formatDateTime(row.sent_at) : '—'),
    },
    {
      key: 'offers_count',
      title: t('bpp.alternatives.feed.offers', 'Альтернатив'),
      align: 'right',
      render: (row) => (
        <span className={row.offers_count === 0 ? 'text-muted-foreground' : undefined}>
          {row.offers_count} / {row.alt_limit}
        </span>
      ),
    },
    {
      key: 'my_offer',
      title: t('bpp.alternatives.feed.mine', 'Моя альтернатива'),
      required: true,
      render: (row) => {
        if (row.my_offer) {
          return (
            <span className="flex flex-wrap items-center gap-2">
              <Link className="text-primary hover:underline" to={offerHref(row.my_offer.id)}>
                {row.my_offer.number}
              </Link>
              <StatusBadge kind="alternative_offer" status={row.my_offer.status} />
            </span>
          );
        }
        return canPropose ? <ProposeButton row={row} /> : '—';
      },
    },
  ], [canPropose, t]);

  const filters = useMemo<RegistryFilter[]>(() => [
    {
      key: 'kind',
      label: t('bpp.alternatives.feed.kind', 'Вид'),
      kind: 'select',
      options: [
        { value: 'invoice', label: t('bpp.alternatives.feed.invoice', 'Счёт') },
        { value: 'agreement', label: t('bpp.alternatives.feed.agreement', 'Договор') },
      ],
    },
    { key: 'amount_from', label: t('bpp.alternatives.feed.amountFrom', 'Сумма от'), kind: 'text' },
    { key: 'amount_to', label: t('bpp.alternatives.feed.amountTo', 'Сумма до'), kind: 'text' },
    { key: 'sent_from', label: t('bpp.alternatives.feed.sentFrom', 'Отправлено с'), kind: 'date' },
    { key: 'sent_to', label: t('bpp.alternatives.feed.sentTo', 'Отправлено по'), kind: 'date' },
    {
      key: 'without_offers',
      label: t('bpp.alternatives.feed.withoutOffers', 'Альтернативы'),
      kind: 'select',
      options: [{ value: '1', label: t('bpp.alternatives.feed.noneYet', 'Без альтернатив') }],
    },
    {
      key: 'mine',
      label: t('bpp.alternatives.feed.mineFilter', 'Мои'),
      kind: 'select',
      options: [
        { value: 'yes', label: t('bpp.alternatives.feed.mineYes', 'Есть моя альтернатива') },
        { value: 'no', label: t('bpp.alternatives.feed.mineNo', 'Моей альтернативы нет') },
      ],
    },
  ], [t]);

  const showAll = () => setSearchParams((current) => {
    const next = new URLSearchParams(current);
    next.delete('source');
    next.delete('page');
    return next;
  }, { replace: true });

  return (
    <div className="space-y-4">
      <h2 className="text-2xl font-bold tracking-tight">
        {t('bpp.alternatives.feed.title', 'Закупки для альтернатив')}
      </h2>
      {source && (
        <div role="note" className="flex flex-wrap items-center gap-2 rounded-md border border-primary/40 bg-primary/5 px-3 py-2 text-sm">
          <span className="font-medium">
            {t('bpp.alternatives.feed.sourceNote', 'Отбор по документу из уведомления')}
          </span>
          <Badge variant="secondary">{source}</Badge>
          <Button variant="ghost" size="sm" className="ml-auto" onClick={showAll}>
            {t('bpp.alternatives.feed.showAll', 'Показать всю ленту')}
          </Button>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2" data-testid="feed-filters">
        <MultiFilter
          label={t('bpp.alternatives.feed.project', 'Проект')}
          options={(projects.data ?? []).map((project) => ({ value: project.id, label: `${project.code} — ${project.name}` }))}
          selected={pageFilters.getAll('project_id')}
          onChange={(values) => setFilter('project_id', values)}
        />
        <MultiFilter
          label={t('bpp.alternatives.feed.article', 'Статья')}
          options={(articles.data ?? []).map((article) => ({ value: article.id, label: `${article.code} — ${article.name}` }))}
          selected={pageFilters.getAll('article_id')}
          onChange={(values) => setFilter('article_id', values)}
        />
        <Select
          value={pageFilters.get('author_id') ?? '__all__'}
          onValueChange={(value) => setFilter('author_id', value === '__all__' ? [] : [value])}
        >
          <SelectTrigger className="h-8 w-48" aria-label={t('bpp.alternatives.feed.author', 'Автор')}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__all__">{t('bpp.alternatives.feed.allAuthors', 'Все авторы')}</SelectItem>
            {Object.entries(authors).map(([id, name]) => (
              <SelectItem key={id} value={id}>{name}</SelectItem>
            ))}
            {pageFilters.get('author_id') && !(pageFilters.get('author_id')! in authors) && (
              <SelectItem value={pageFilters.get('author_id')!}>{pageFilters.get('author_id')}</SelectItem>
            )}
          </SelectContent>
        </Select>
        <div className="w-64">
          <CounterpartyPicker
            value={counterparty}
            onChange={(brief) => { setCounterparty(brief); setFilter('counterparty_id', [brief.id]); }}
          />
        </div>
        {pageFilters.get('counterparty_id') && (
          <Button type="button" variant="ghost" size="sm"
            onClick={() => { setCounterparty(null); setFilter('counterparty_id', []); }}>
            <X className="mr-1 h-3.5 w-3.5" />
            {t('bpp.alternatives.feed.clearCounterparty', 'Сбросить контрагента')}
          </Button>
        )}
      </div>
      <BppRegistry<FeedRow>
        key={`${source ?? 'all'}|${pageFiltersKey}`}
        registryKey="alternatives"
        endpoint={feedEndpoint(source, pageFilters)}
        columns={columns}
        filters={filters}
        mapItems={mapRows}
        searchParam="q"
        searchPlaceholder={t('bpp.alternatives.feed.search', 'Наименование позиции')}
        rowHref={(row) => row.url}
        rowLabel={(row) => row.number}
      />
    </div>
  );
}

export default AlternativesFeedPage;
