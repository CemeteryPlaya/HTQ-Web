/**
 * Карточка заявки на тендер (`/tender/requests/:id`, T1.4; план §3.3–3.5).
 *
 * - Кнопки — ровно по `allowed_actions` сервера: «Редактировать» (`save`) —
 *   ссылкой на форму, «Отправить», «Отозвать», «Отменить» (комментарий от
 *   10 символов), «Удалить» — кнопками документа БЗО (`DocumentActionButton`:
 *   блокировка до ответа, `Idempotency-Key`, ошибка — тостом).
 * - Части — ЗЗ модуля БЗО, на которые сервер разрезал заявку при отправке:
 *   номер ссылкой на её карточку в «Закупках и оплатах», статус — тот же
 *   бейдж, что в БЗО. «Исключить часть» — только у отклонённой части.
 * - Отказ 409 `E-CON-01` — плашка «заявку уже изменили» с «Обновить».
 */
import { useCallback, useState, type ReactNode } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { AlertTriangle, Pencil } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table, TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { DocumentActionButton, type BppDocumentAction } from '@/features/bpp/core/DocumentActionButton';
import { StatusBadge } from '@/features/bpp/core/StatusBadge';
import { formatDate, formatMoney } from '@/features/bpp/format';
import { lineAmount } from '@/features/bpp/requests/requestForm';
import { sumMoney } from '@/features/bpp/budgets/cents';
import { usePermissions } from '@/hooks/usePermissions';
import { errorStatus } from '@/lib/apiError';

import { ConflictAlert } from '../core/ConflictAlert';
import { isConflict } from '../core/conflict';
import { TenderStatusBadge } from '../core/TenderStatusBadge';
import {
  bppRequestHref, TENDER_REQUESTS_BASE, tenderRequestHref, tenderRequestKeys, tenderRequestsApi,
  type TenderRequestCard, type TenderRequestPart,
} from './api';
import { tenderHref, tendersApi } from '../tenders/api';
import { BackToRequests } from './BackToRequests';
import { PART_KIND_LABELS, PURCHASE_TYPE_LABELS, ROLE_LABELS } from './labels';
import { COMMENT_MIN } from './requestForm';
import { useArticleNames, useUomNames } from './reference';

const KZT = 'KZT';

function Detail({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="space-y-0.5">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-sm">{children}</dd>
    </div>
  );
}

export function RequestCardPage() {
  const { t } = useTranslation();
  const { id = '' } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const permissions = usePermissions();
  const [conflict, setConflict] = useState(false);
  const [busy, setBusy] = useState<Record<string, boolean>>({});

  const { data: card, isLoading, error, refetch } = useQuery({
    queryKey: tenderRequestKeys.card(id),
    queryFn: () => tenderRequestsApi.get(id),
    enabled: Boolean(id),
  });
  const articles = useArticleNames();
  const uoms = useUomNames();

  const onPendingChange = useCallback((key: string, pending: boolean) => {
    setBusy((current) => (current[key] === pending ? current : { ...current, [key]: pending }));
  }, []);
  const onDone = useCallback(() => undefined, []);

  if (isLoading) return <Skeleton className="h-64 w-full" />;
  if (error || !card) {
    return (
      <div className="space-y-2">
        <BackToRequests />
        <p className="text-sm text-muted-foreground">
          {errorStatus(error) === 404
            ? t('tender.requests.notFound', 'Заявка не найдена или недоступна.')
            : t('tender.requests.loadFailed', 'Не удалось загрузить заявку.')}
        </p>
      </div>
    );
  }

  const apply = (saved: TenderRequestCard) => {
    setConflict(false);
    queryClient.setQueryData(tenderRequestKeys.card(saved.id), saved);
    void queryClient.invalidateQueries({ queryKey: [...tenderRequestKeys.all, 'list'] });
  };
  /** Действие документа: 409 E-CON-01 поднимает плашку, ошибка уходит в тост кнопки. */
  const guarded = (run: BppDocumentAction['run']): BppDocumentAction['run'] => async (key, comment) => {
    try {
      return await run(key, comment);
    } catch (failure) {
      if (isConflict(failure)) setConflict(true);
      throw failure;
    }
  };

  const allowed = card.allowed_actions;
  const anyBusy = Object.values(busy).some(Boolean);
  const actions: [string, BppDocumentAction][] = ([
    ['submit', {
      label: t('tender.requests.submit', 'Отправить на согласование'),
      run: guarded(async (key) => apply(await tenderRequestsApi.submit(card.id, key, card.version))),
    }],
    ['withdraw', {
      label: t('tender.requests.withdraw', 'Отозвать'),
      variant: 'outline',
      confirm: {
        title: t('tender.requests.withdrawConfirm', 'Отозвать заявку с согласования? Её ЗЗ в БЗО будут отозваны.'),
      },
      run: guarded(async (key) => apply(await tenderRequestsApi.withdraw(card.id, key, card.version))),
    }],
    ['cancel', {
      label: t('tender.requests.cancel', 'Отменить заявку'),
      variant: 'outline',
      confirm: {
        title: t('tender.requests.cancelConfirm', 'Отменить заявку? Её ЗЗ в БЗО тоже будут отменены.'),
        commentMin: COMMENT_MIN,
      },
      run: guarded(async (key, comment) =>
        apply(await tenderRequestsApi.cancel(card.id, key, card.version, comment ?? ''))),
    }],
    ['delete', {
      label: t('tender.requests.delete', 'Удалить'),
      variant: 'destructive',
      confirm: { title: t('tender.requests.deleteConfirm', 'Удалить черновик заявки?') },
      run: guarded(async (key) => {
        await tenderRequestsApi.remove(card.id, key, card.version);
        void queryClient.invalidateQueries({ queryKey: [...tenderRequestKeys.all, 'list'] });
        navigate(TENDER_REQUESTS_BASE);
      }),
    }],
  ] as [string, BppDocumentAction][]).filter(([key]) => allowed.includes(key));
  // Тендер объявляется только из утверждённой заявки (план §4.2; иначе 409
  // E-STS-01, второй активный — 409 E-TND-01: текст сервера уйдёт в тост).
  if (card.status === 'approved' && permissions.can('tender.tenders', 'create')) {
    actions.unshift(['announce', {
      label: t('tender.requests.announce', 'Объявить тендер'),
      run: async (key) => {
        const tender = await tendersApi.create(key, card.id);
        void queryClient.invalidateQueries({ queryKey: ['tender', 'tenders'] });
        navigate(tenderHref(tender.id));
      },
    }]);
  }

  const excludeAction = (part: TenderRequestPart): BppDocumentAction => ({
    label: t('tender.requests.excludePart', 'Исключить часть'),
    variant: 'outline',
    confirm: {
      title: t('tender.requests.excludeConfirm', 'Исключить часть {{number}} из заявки?', {
        number: part.bpp_number,
      }),
      description: t(
        'tender.requests.excludeHint',
        'Позиции этой части будут удалены из заявки, статус заявки пересчитается по остальным частям.',
      ),
    },
    run: guarded(async (key) =>
      apply(await tenderRequestsApi.excludePart(card.id, part.id, key, card.version))),
  });

  const articleName = (articleId: string | null) =>
    (articleId ? articles.get(articleId) ?? '—' : '—');
  const label = (dict: Record<string, { key: string; fallback: string }>, code: string) =>
    (dict[code] ? t(dict[code].key, dict[code].fallback) : code || '—');
  const yesNo = (value: boolean) => (value ? t('tender.requests.yes', 'Да') : t('tender.requests.no', 'Нет'));
  const total = sumMoney(card.items.map((item) => lineAmount(item.qty, item.plan_price)));

  return (
    <div className="space-y-6">
      <BackToRequests />

      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-2xl font-bold">
          {t('tender.requests.cardTitle', 'Заявка на тендер {{number}}', { number: card.number })}
        </h2>
        <TenderStatusBadge status={card.status} />
      </div>

      {conflict && (
        <ConflictAlert
          message={t(
            'tender.requests.conflict',
            'Заявку уже изменили — в другом окне или другой пользователь. Обновите её и повторите действие.',
          )}
          onReload={() => { setConflict(false); void refetch(); }}
        />
      )}

      {card.status === 'rework' && card.rework_comment && (
        <div
          role="status"
          className="flex gap-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm dark:border-amber-800 dark:bg-amber-950/40"
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <div>
            <div className="font-medium">{t('tender.requests.reworkTitle', 'Заявка возвращена на доработку')}</div>
            <div>{card.rework_comment}</div>
          </div>
        </div>
      )}
      {card.status_comment && (
        <p className="text-sm text-muted-foreground">
          {t('tender.requests.statusComment', 'Комментарий к статусу')}: {card.status_comment}
        </p>
      )}

      {(allowed.includes('save') || actions.length > 0) && (
        <div className="flex flex-wrap gap-2">
          {allowed.includes('save') && (
            <Button asChild variant="outline">
              <Link to={`${tenderRequestHref(card.id)}/edit`}>
                <Pencil className="mr-1.5 h-4 w-4" />
                {t('tender.requests.edit', 'Редактировать')}
              </Link>
            </Button>
          )}
          {actions.map(([key, action]) => (
            <DocumentActionButton
              key={key}
              actionKey={key}
              action={action}
              disabled={anyBusy && !busy[key]}
              onPendingChange={onPendingChange}
              onDone={onDone}
            />
          ))}
        </div>
      )}

      <dl className="grid gap-4 rounded-2xl border bg-card p-4 sm:grid-cols-2 lg:grid-cols-3">
        <Detail label={t('tender.requests.project', 'Проект')}>
          {card.project ? `${card.project.code} — ${card.project.name}` : '—'}
        </Detail>
        <Detail label={t('tender.requests.author', 'Автор')}>
          {card.author_name || '—'}
        </Detail>
        <Detail label={t('tender.requests.role', 'Роль инициатора')}>
          {label(ROLE_LABELS, card.initiator_role)}
        </Detail>
        <Detail label={t('tender.requests.article', 'Статья бюджета')}>
          {articleName(card.article_id)}
        </Detail>
        <Detail label={t('tender.requests.purchaseType', 'Вид закупки')}>
          {label(PURCHASE_TYPE_LABELS, card.purchase_type)}
        </Detail>
        <Detail label={t('tender.requests.needDate', 'Потребность к дате')}>
          {formatDate(card.need_date)}
        </Detail>
        <Detail label={t('tender.requests.deliveryAddress', 'Адрес доставки')}>
          {card.delivery_address || '—'}
        </Detail>
        <Detail label={t('tender.requests.allowAnalogs', 'Допускаются аналоги')}>
          {yesNo(card.allow_analogs)}
        </Detail>
        <Detail label={t('tender.requests.allowPartial', 'Допускается частичная поставка')}>
          {yesNo(card.allow_partial)}
        </Detail>
        {card.needs_delivery && (
          <Detail label={t('tender.requests.delivery', 'Доставка до объекта')}>
            {articleName(card.delivery_article_id)}
            {card.delivery_plan_amount && ` · ${formatMoney(card.delivery_plan_amount, KZT)}`}
          </Detail>
        )}
        {card.needs_works && (
          <Detail label={t('tender.requests.works', 'СМР')}>
            <div className="whitespace-pre-wrap">{card.works_scope || '—'}</div>
            <div className="text-muted-foreground">
              {articleName(card.works_article_id)}
              {card.works_plan_amount && ` · ${formatMoney(card.works_plan_amount, KZT)}`}
            </div>
          </Detail>
        )}
        <div className="sm:col-span-2 lg:col-span-3">
          <Detail label={t('tender.requests.justification', 'Обоснование потребности')}>
            <span className="whitespace-pre-wrap">{card.justification || '—'}</span>
          </Detail>
        </div>
      </dl>

      <section className="space-y-2">
        <h3 className="text-lg font-semibold">{t('tender.requests.items', 'Позиции')}</h3>
        <div className="overflow-x-auto rounded-2xl border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10">№</TableHead>
                <TableHead>{t('tender.requests.itemName', 'Наименование')}</TableHead>
                <TableHead>{t('tender.requests.itemSpecs', 'Характеристики')}</TableHead>
                <TableHead>{t('tender.requests.itemUom', 'Ед.')}</TableHead>
                <TableHead className="text-right">{t('tender.requests.itemQty', 'Кол-во')}</TableHead>
                <TableHead className="text-right">{t('tender.requests.itemPrice', 'Плановая цена')}</TableHead>
                <TableHead className="text-right">{t('tender.requests.itemAmount', 'Сумма')}</TableHead>
                <TableHead>{t('tender.requests.needDate', 'Потребность к дате')}</TableHead>
                <TableHead>{t('tender.requests.itemArticle', 'Статья')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {card.items.length === 0 && (
                <TableRow>
                  <TableCell colSpan={9} className="text-center text-muted-foreground">
                    {t('tender.requests.noItems', 'Позиций нет')}
                  </TableCell>
                </TableRow>
              )}
              {card.items.map((item) => {
                const amount = lineAmount(item.qty, item.plan_price);
                return (
                  <TableRow key={item.id}>
                    <TableCell>{item.line_no}</TableCell>
                    <TableCell>{item.name}</TableCell>
                    <TableCell>{item.specs || '—'}</TableCell>
                    <TableCell>{uoms.get(item.uom_id) ?? '—'}</TableCell>
                    <TableCell className="text-right">{item.qty.replace('.', ',')}</TableCell>
                    <TableCell className="text-right">{formatMoney(item.plan_price)}</TableCell>
                    <TableCell className="text-right">{amount === null ? '—' : formatMoney(amount)}</TableCell>
                    <TableCell>{formatDate(item.need_date)}</TableCell>
                    <TableCell>
                      {item.article_id
                        ? articleName(item.article_id)
                        : <span className="text-muted-foreground">{t('tender.requests.byRequestArticle', 'по статье заявки')}</span>}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
            <TableFooter>
              <TableRow>
                <TableCell colSpan={6}>{t('tender.requests.itemsTotal', 'Плановая сумма позиций')}</TableCell>
                <TableCell className="text-right">{formatMoney(total, KZT)}</TableCell>
                <TableCell colSpan={2} />
              </TableRow>
            </TableFooter>
          </Table>
        </div>
      </section>

      <section className="space-y-2">
        <h3 className="text-lg font-semibold">{t('tender.requests.parts', 'Части заявки в БЗО')}</h3>
        {card.parts.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {t('tender.requests.noParts',
              'Части появятся после отправки: заявка разделится на ЗЗ по статьям бюджета.')}
          </p>
        ) : (
          <div className="overflow-x-auto rounded-2xl border bg-card">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('tender.requests.partKind', 'Часть')}</TableHead>
                  <TableHead>{t('tender.requests.itemArticle', 'Статья')}</TableHead>
                  <TableHead>{t('tender.requests.partNumber', 'Заявка на закупку')}</TableHead>
                  <TableHead>{t('tender.requests.status', 'Статус')}</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {card.parts.map((part) => {
                  const excludable = allowed.includes('exclude')
                    && part.bpp_status === 'rejected' && !part.excluded_at;
                  return (
                    <TableRow key={part.id} className={part.excluded_at ? 'opacity-60' : undefined}>
                      <TableCell>{label(PART_KIND_LABELS, part.kind)}</TableCell>
                      <TableCell>{articleName(part.article_id)}</TableCell>
                      <TableCell>
                        {part.bpp_request_id && part.bpp_number ? (
                          <Link to={bppRequestHref(part.bpp_request_id)} className="text-primary hover:underline">
                            {part.bpp_number}
                          </Link>
                        ) : part.bpp_number || '—'}
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap items-center gap-2">
                          {part.bpp_status && <StatusBadge kind="request" status={part.bpp_status} />}
                          {part.excluded_at && (
                            <span className="text-xs text-muted-foreground">
                              {t('tender.requests.excludedAt', 'Исключена {{date}}', {
                                date: formatDate(part.excluded_at),
                              })}
                            </span>
                          )}
                        </div>
                      </TableCell>
                      <TableCell className="text-right">
                        {excludable && (
                          <DocumentActionButton
                            actionKey={`exclude:${part.id}`}
                            action={excludeAction(part)}
                            disabled={anyBusy && !busy[`exclude:${part.id}`]}
                            onPendingChange={onPendingChange}
                            onDone={onDone}
                          />
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        )}
      </section>
    </div>
  );
}

export default RequestCardPage;
