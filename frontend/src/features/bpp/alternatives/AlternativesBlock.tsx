/**
 * Блок «Альтернативы» форм договора (F-04) и счёта без договора (F-05) —
 * ТЗ §12.4 п.2: исходный документ и поданные альтернативы в колонках, по
 * строкам — контрагент, сумма, НДС, экономия, срок, условия оплаты, КП,
 * автор, статус; ниже — цены по позициям.
 *
 * - «Предложить альтернативу» — `can_propose` сравнения (право, окно подачи,
 *   лимиты, вид документа); заводит черновик и открывает форму F-07.
 * - «Моя альтернатива» — ссылка на АП автора (`my_offer_id`); чужой черновик
 *   не показывается (сервер его и не присылает, здесь — вторая линия).
 * - Отозванные и аннулированные АП остаются в таблице приглушёнными, с
 *   бейджем статуса. Срок исходного документа — «Потребность» позиций
 *   (нет даты — ячейка пуста). Знак отклонения — плюс: АП дороже исходного.
 * - `renderSelect` — слот для кнопки «Выбрать» (B5.1); зовётся для каждой
 *   АП «Подано». Блок сам ничего не выбирает.
 * - Автор документа-СН (автор и держатель `bpp.alternatives` create) поднимает
 *   лимит альтернатив (по умолчанию 3, до 10); ПМ-автору поле не показывается.
 * - Нет права `bpp.alternatives` view — сравнение не запрашивается и блока
 *   нет; документ не виден или альтернатив нет и подать нельзя — тоже.
 */
import { useState, type ReactNode } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate } from 'react-router-dom';
import { Loader2 } from 'lucide-react';

import { newIdempotencyKey } from '@/api/files';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useActiveProfile } from '@/hooks/useActiveProfile';
import { usePermissions } from '@/hooks/usePermissions';
import { reportApiError } from '@/lib/apiError';
import { cn } from '@/lib/utils';

import { ComparisonGrid } from '../core/ComparisonGrid';
import { StatusBadge } from '../core/StatusBadge';
import { formatDate, formatMoney } from '../format';

import {
  alternativesApi, comparisonKey, offerHref, paymentTermsLabel, type Comparison,
  type ComparisonOffer, type SourceType,
} from './api';
import { deviationText, isDearer, savingText } from './offerForm';
import { savingFromString } from './money';

const ORANGE = 'text-amber-700 dark:text-amber-400';
const LIMIT_MAX = 10;
const INACTIVE = ['withdrawn', 'annulled', 'not_selected'];

interface Props {
  sourceType: SourceType;
  sourceId: string;
  /** Слот кнопки «Выбрать» (B5.1) для каждой АП «Подано». */
  renderSelect?: (offer: ComparisonOffer) => ReactNode;
}

export function AlternativesBlock({ sourceType, sourceId, renderSelect }: Props) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const profile = useActiveProfile();
  const permissions = usePermissions();
  const canView = permissions.can('bpp.alternatives', 'view');
  const currentUserId = parseInt(profile.activeProfile?.id ?? '0', 10) || 0;
  const [creating, setCreating] = useState(false);
  const [limit, setLimit] = useState('');
  const [raising, setRaising] = useState(false);

  const { data } = useQuery({
    queryKey: comparisonKey(sourceType, sourceId),
    queryFn: () => alternativesApi.comparison(sourceType, sourceId),
    retry: false,
    enabled: canView,
  });
  if (!canView || !data || !Array.isArray(data.offers)) return null;

  const offers = data.offers.filter((offer) => offer.status !== 'draft' || offer.id === data.my_offer_id);
  if (offers.length === 0 && !data.can_propose && !data.my_offer_id) return null;

  const propose = async () => {
    setCreating(true);
    try {
      const created = await alternativesApi.create(newIdempotencyKey(), sourceType, sourceId);
      void queryClient.invalidateQueries({ queryKey: comparisonKey(sourceType, sourceId) });
      navigate(offerHref(created.id));
    } catch (error) {
      reportApiError(error, t('bpp.alternatives.createFailed', 'Не удалось начать альтернативу'));
    } finally {
      setCreating(false);
    }
  };

  // Лимит поднимает автор документа-СН (сервер: автор, роль СН и create);
  // ПМ-автор без create получил бы 403 — поля у него нет.
  const canRaiseLimit = data.source.author.id === currentUserId
    && permissions.can('bpp.alternatives', 'create');
  const limitNumber = Number(limit);
  const limitValid = Number.isInteger(limitNumber)
    && limitNumber >= Math.max(data.submitted_count, data.limit) && limitNumber <= LIMIT_MAX;
  const raise = async () => {
    setRaising(true);
    try {
      await alternativesApi.setLimit(sourceType, sourceId, newIdempotencyKey(), limitNumber);
      setLimit('');
      await queryClient.invalidateQueries({ queryKey: comparisonKey(sourceType, sourceId) });
    } catch (error) {
      reportApiError(error, t('bpp.alternatives.limitFailed', 'Не удалось поднять лимит'));
    } finally {
      setRaising(false);
    }
  };

  const dim = (offer: ComparisonOffer) => (INACTIVE.includes(offer.status) ? 'opacity-50' : undefined);

  return (
    <section className="space-y-3" aria-label={t('bpp.alternatives.blockTitle', 'Альтернативы')} data-testid="alternatives-block">
      <div className="flex flex-wrap items-center gap-3">
        <h3 className="text-lg font-semibold">{t('bpp.alternatives.blockTitle', 'Альтернативы')}</h3>
        <span className="text-sm text-muted-foreground">
          {t('bpp.alternatives.submittedOf', 'Подано {{n}} из {{limit}}', {
            n: data.submitted_count, limit: data.limit,
          })}
        </span>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {data.my_offer_id && (
            <Button asChild variant="outline" size="sm">
              <Link to={offerHref(data.my_offer_id)}>{t('bpp.alternatives.myOffer', 'Моя альтернатива')}</Link>
            </Button>
          )}
          {data.can_propose && (
            <Button type="button" size="sm" disabled={creating} onClick={propose}>
              {creating && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
              {t('bpp.alternatives.propose', 'Предложить альтернативу')}
            </Button>
          )}
        </div>
      </div>

      {canRaiseLimit && data.window_open && data.limit < LIMIT_MAX && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <label htmlFor="alt-limit">{t('bpp.alternatives.limitLabel', 'Лимит альтернатив')}:</label>
          <Input id="alt-limit" className="w-20 text-right" inputMode="numeric" value={limit}
            placeholder={String(data.limit)} onChange={(event) => setLimit(event.target.value)} />
          <Button type="button" size="sm" variant="outline" disabled={!limitValid || raising} onClick={raise}>
            {t('bpp.alternatives.raiseLimit', 'Поднять')}
          </Button>
          <span className="text-xs text-muted-foreground">
            {t('bpp.alternatives.limitHint', 'от {{min}} до {{max}}', {
              min: Math.max(data.submitted_count, data.limit), max: LIMIT_MAX,
            })}
          </span>
        </div>
      )}

      {offers.length > 0 && <ComparisonTable data={data} offers={offers} dim={dim} renderSelect={renderSelect} />}
      {offers.length === 0 && (
        <p className="text-sm text-muted-foreground">
          {t('bpp.alternatives.none', 'Альтернатив пока нет.')}
        </p>
      )}
    </section>
  );
}

interface InfoRow {
  key: string;
  label: string;
  source: ReactNode;
  offer: (offer: ComparisonOffer) => ReactNode;
}

function ComparisonTable({ data, offers, dim, renderSelect }: {
  data: Comparison;
  offers: ComparisonOffer[];
  dim: (offer: ComparisonOffer) => string | undefined;
  renderSelect?: (offer: ComparisonOffer) => ReactNode;
}) {
  const { t } = useTranslation();
  const { source } = data;
  const cpName = (cp: { short_name: string; name: string; country_name?: string | null; country_code: string } | null) =>
    cp ? `${cp.short_name || cp.name} · ${cp.country_name ?? cp.country_code}` : '—';
  const noVat = t('bpp.alternatives.noVat', 'без НДС');
  const info: InfoRow[] = [
    { key: 'counterparty', label: t('bpp.alternatives.counterparty', 'Контрагент'),
      source: cpName(source.counterparty), offer: (offer) => cpName(offer.counterparty) },
    { key: 'amount', label: t('bpp.alternatives.amount', 'Сумма'),
      source: source.amount ? formatMoney(source.amount, source.currency_code) : '—',
      offer: (offer) => (offer.amount ? formatMoney(offer.amount, offer.currency_code) : '—') },
    { key: 'amount_kzt', label: t('bpp.alternatives.amountKzt', 'В тенге'),
      source: source.amount_kzt ? formatMoney(source.amount_kzt, 'KZT') : '—',
      offer: (offer) => (offer.amount_kzt ? formatMoney(offer.amount_kzt, 'KZT') : '—') },
    { key: 'vat', label: t('bpp.alternatives.vat', 'НДС'),
      source: source.with_vat ? `${source.vat_rate ?? ''}%` : noVat,
      offer: (offer) => (offer.with_vat ? `${offer.vat_rate ?? ''}%` : noVat) },
    { key: 'saving', label: t('bpp.alternatives.saving', 'Экономия'), source: '—', offer: (offer) => {
      const value = offer.saving.amount !== null && offer.saving.pct !== null
        ? savingFromString(offer.saving.amount, offer.saving.pct) : null;
      if (!value) return '—';
      return (
        <span className={cn('font-medium', value.moreExpensive && ORANGE)}>
          {savingText(value, 'KZT', t('bpp.alternatives.dearer', 'Дороже на'))}
        </span>
      );
    } },
    { key: 'term', label: t('bpp.alternatives.term', 'Срок поставки'),
      source: source.delivery_date
        ? `${t('bpp.alternatives.need', 'Потребность')}: ${formatDate(source.delivery_date)}`
        : '',
      offer: (offer) => formatDate(offer.delivery_date) },
    { key: 'payment', label: t('bpp.alternatives.paymentTerms', 'Условия оплаты'), source: '—',
      offer: (offer) => paymentTermsLabel(offer.payment_terms, t) },
    { key: 'files', label: t('bpp.alternatives.offerFiles', 'КП'), source: '—',
      offer: (offer) => (offer.files.length > 0 ? offer.files.map((file) => file.filename ?? file.id).join(', ') : '—') },
    { key: 'author', label: t('bpp.alternatives.author', 'Автор'), source: source.author.name ?? '—',
      offer: (offer) => offer.author.name ?? '—' },
  ];
  const offerKey = (offer: ComparisonOffer) => offer.id;

  return (
    <div className="space-y-4 overflow-x-auto">
      <ComparisonGrid
        columns={offers}
        columnKey={offerKey}
        dim={dim}
        renderColumn={(offer) => (
          <>
            <Link className="text-primary hover:underline" to={offerHref(offer.id)}>{offer.number}</Link>
            <span className="mt-1 block"><StatusBadge kind="alternative_offer" status={offer.status} /></span>
          </>
        )}
        leading={[{
          key: 'source',
          header: (
            <>
              <Link className="text-primary hover:underline" to={source.url}>{source.number}</Link>
              <span className="block text-xs font-normal text-muted-foreground">
                {t('bpp.alternatives.original', 'Исходный документ')}
              </span>
            </>
          ),
          cell: (row: InfoRow) => row.source,
        }]}
        rows={info}
        rowKey={(row) => row.key}
        renderRow={(row) => row.label}
        cell={(row, offer) => row.offer(offer)}
        footer={renderSelect
          ? (offer) => (offer.status === 'submitted' ? renderSelect(offer) : null)
          : undefined}
      />

      <ComparisonGrid
        columns={offers}
        columnKey={offerKey}
        dim={dim}
        cellClassName="text-right"
        rowHeader={t('bpp.alternatives.item', 'Позиция')}
        rowHeadClassName="whitespace-normal"
        renderColumn={(offer) => offer.number}
        leading={[
          { key: 'qty', className: 'text-right', header: t('bpp.alternatives.qty', 'Кол-во'),
            cell: (position: Comparison['positions'][number]) => `${position.qty} ${position.uom ?? ''}` },
          { key: 'price', className: 'text-right', header: t('bpp.alternatives.sourcePrice', 'Цена исходная'),
            cell: (position: Comparison['positions'][number]) => formatMoney(position.source_price) },
        ]}
        rows={data.positions}
        rowKey={(position) => position.source_line_id}
        renderRow={(position) => position.name}
        cell={(position, offer) => {
          const value = position.offers[offer.id];
          return value?.price ? (
            <>
              {formatMoney(value.price)}
              <span className={cn('block text-xs', isDearer(value.deviation_pct) ? ORANGE : 'text-muted-foreground')}>
                {deviationText(value.deviation_pct)}
              </span>
            </>
          ) : '—';
        }}
      />
    </div>
  );
}

export default AlternativesBlock;
