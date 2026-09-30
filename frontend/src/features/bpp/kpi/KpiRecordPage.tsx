/**
 * Карточка записи KPI (ТЗ §12.5–12.6; A5.2): ссылки на исходный документ,
 * альтернативное предложение и новый документ, статус, признак «К своему
 * документу», журнал изменений. «Аннулировать» — только с `bpp.kpi` edit (ФД)
 * и пока запись не аннулирована; комментарий не короче 10 знаков (BR-060).
 * После аннулирования перечитываются карточка и отчёт (`KPI_KEY`); отказ 409
 * (запись успели подтвердить или аннулировать системой) перечитывает карточку,
 * чтобы повтор ушёл с новой `version`.
 *
 * Журнал — подписи полей, суммы в формате модуля и подписи статусов
 * (`changes` пишет `services/alternatives/kpi.py`).
 */
import { useMemo, useState, type ReactNode } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import type { TFunction } from 'i18next';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { usePermissions } from '@/hooks/usePermissions';
import { errorStatus } from '@/lib/apiError';

import { CommentDialog } from '../core/CommentDialog';
import { HistoryTab } from '../core/HistoryTab';
import { StatusBadge } from '../core/StatusBadge';
import { STATUS_DICTIONARIES } from '../core/statusDictionaries';
import { formatDateTime, formatMoney } from '../format';
import { projectApi, projectKeys } from '../projects/api';
import { refdataApi, refdataKeys } from '../refdata/api';

import { KPI_BASE, KPI_KEY, kpiApi, kpiKeys } from './api';

const KZT = 'KZT';

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="space-y-0.5">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-sm">{children}</dd>
    </div>
  );
}

const money = (value: string | null) => (value === null ? '—' : formatMoney(value, KZT));

/** Поля `changes` журнала записи KPI (`services/alternatives/kpi.py`). */
const HISTORY_MONEY = ['source_amount_kzt', 'result_amount_kzt', 'saving_amount'] as const;

const historyFieldLabels = (t: TFunction): Record<string, string> => ({
  offer: t('bpp.kpi.offer', 'Альтернативное предложение'),
  source: t('bpp.kpi.source', 'Исходный документ'),
  result: t('bpp.kpi.result', 'Новый документ'),
  result_number: t('bpp.kpi.resultNumber', 'Номер нового документа'),
  source_amount_kzt: t('bpp.kpi.sourceAmount', 'Исходная сумма'),
  result_amount_kzt: t('bpp.kpi.resultAmount', 'Сумма нового документа'),
  saving_amount: t('bpp.kpi.savingAmount', 'Экономия'),
  status: t('bpp.kpi.status', 'Статус'),
});

const historyValueLabels = (t: TFunction): Record<string, Record<string, string>> => ({
  status: Object.fromEntries(Object.entries(STATUS_DICTIONARIES.kpi_record)
    .map(([code, def]) => [code, t(def.labelKey, def.label)])),
});

export function KpiRecordPage() {
  const { t } = useTranslation();
  const { id = '' } = useParams();
  const queryClient = useQueryClient();
  const permissions = usePermissions();
  const [annulling, setAnnulling] = useState(false);
  const fieldLabels = useMemo(() => historyFieldLabels(t), [t]);
  const valueLabels = useMemo(() => historyValueLabels(t), [t]);

  const record = useQuery({
    queryKey: kpiKeys.card(id),
    queryFn: () => kpiApi.card(id),
    enabled: Boolean(id),
    retry: false,
  });
  const projects = useQuery({
    queryKey: projectKeys.list('', false),
    queryFn: () => projectApi.list('', false),
    staleTime: 5 * 60 * 1000,
  });
  const articles = useQuery({
    queryKey: refdataKeys.list('articles'),
    queryFn: () => refdataApi.articles.list(),
    staleTime: 5 * 60 * 1000,
  });

  const typeLabel = (type: string) => (type === 'invoice'
    ? t('bpp.kpi.doc.invoice', 'Счёт')
    : type === 'agreement' ? t('bpp.kpi.doc.agreement', 'Договор') : type);

  const back = (
    <Link to={KPI_BASE} className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
      <ArrowLeft className="h-4 w-4" />
      {t('bpp.kpi.backToReport', 'К отчёту «KPI снабжения»')}
    </Link>
  );

  if (record.isLoading) return <Skeleton className="h-64 w-full" />;
  if (record.isError || !record.data) {
    return (
      <div className="space-y-3">
        {back}
        <p role="alert" className="rounded-lg border p-6 text-center text-sm text-muted-foreground">
          {errorStatus(record.error) === 404
            ? t('bpp.kpi.notFound', 'Запись KPI не найдена')
            : t('bpp.kpi.cardFailed', 'Не удалось загрузить запись KPI')}
        </p>
      </div>
    );
  }

  const item = record.data;
  const project = projects.data?.find((p) => p.id === item.project_id);
  const article = articles.data?.find((a) => a.id === item.article_id);
  const canAnnul = permissions.can('bpp.kpi', 'edit') && item.status !== 'annulled';

  const link = (to: string, text: string) => (
    <Link to={to} className="text-primary hover:underline">{text}</Link>
  );

  return (
    <div className="space-y-6">
      {back}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-2xl font-bold tracking-tight">
            {t('bpp.kpi.recordTitle', 'Запись KPI — {{number}}', { number: item.offer_number })}
          </h2>
          <StatusBadge kind="kpi_record" status={item.status} />
          {item.own_document && (
            <span className="rounded border px-2 py-0.5 text-xs" data-testid="own-document">
              {t('bpp.kpi.col.own', 'К своему документу')}
            </span>
          )}
        </div>
        {canAnnul && (
          <Button type="button" variant="destructive" onClick={() => setAnnulling(true)}>
            {t('bpp.kpi.annul', 'Аннулировать')}
          </Button>
        )}
      </div>

      <Card>
        <CardHeader><CardTitle className="text-base">{t('bpp.kpi.documents', 'Документы')}</CardTitle></CardHeader>
        <CardContent>
          <dl className="grid gap-4 sm:grid-cols-3">
            <Field label={t('bpp.kpi.source', 'Исходный документ')}>
              {link(item.source_url, `${typeLabel(item.source_type)} ${item.source_number}`)}
            </Field>
            <Field label={t('bpp.kpi.offer', 'Альтернативное предложение')}>
              {link(item.offer_url, item.offer_number)}
            </Field>
            <Field label={t('bpp.kpi.result', 'Новый документ')}>
              {link(item.result_url, `${typeLabel(item.result_type)} ${item.result_number}`)}
            </Field>
            <Field label={t('bpp.kpi.buyer', 'Снабженец')}>{item.buyer_name}</Field>
            <Field label={t('bpp.kpi.project', 'Проект')}>
              {project ? `${project.code} — ${project.name}` : '—'}
            </Field>
            <Field label={t('bpp.kpi.article', 'Статья')}>
              {article ? `${article.code} — ${article.name}` : '—'}
            </Field>
          </dl>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-base">{t('bpp.kpi.amounts', 'Суммы')}</CardTitle></CardHeader>
        <CardContent>
          <dl className="grid gap-4 sm:grid-cols-4">
            <Field label={t('bpp.kpi.sourceAmount', 'Исходная сумма')}>{money(item.source_amount_kzt)}</Field>
            <Field label={t('bpp.kpi.resultAmount', 'Сумма нового документа')}>{money(item.result_amount_kzt)}</Field>
            <Field label={t('bpp.kpi.savingAmount', 'Экономия')}>{money(item.saving_amount)}</Field>
            <Field label={t('bpp.kpi.savingPct', 'Экономия, %')}>
              {item.saving_pct === null ? '—' : `${item.saving_pct.replace('.', ',')} %`}
            </Field>
            <Field label={t('bpp.kpi.selectedAt', 'Выбрано')}>{formatDateTime(item.selected_at)}</Field>
            <Field label={t('bpp.kpi.statusChanged', 'Статус изменён')}>
              {item.status_changed_at ? formatDateTime(item.status_changed_at) : '—'}
            </Field>
          </dl>
          {item.status === 'annulled' && item.annul_comment && (
            <p className="mt-4 text-sm" data-testid="annul-comment">
              <span className="text-muted-foreground">{t('bpp.kpi.annulComment', 'Причина аннулирования')}: </span>
              {item.annul_comment}
            </p>
          )}
        </CardContent>
      </Card>

      <section className="space-y-2">
        <h3 className="text-base font-semibold">{t('bpp.kpi.history', 'История изменений')}</h3>
        <HistoryTab
          objectType="bpp.kpirecord"
          objectId={item.id}
          fieldLabels={fieldLabels}
          moneyFields={HISTORY_MONEY}
          valueLabels={valueLabels}
        />
      </section>

      {annulling && (
        <CommentDialog
          title={t('bpp.kpi.annulTitle', 'Аннулировать запись KPI')}
          description={t('bpp.kpi.annulHint', 'Запись не будет учитываться в отчёте. Действие необратимо.')}
          submitLabel={t('bpp.kpi.annul', 'Аннулировать')}
          destructive
          failureText={t('bpp.kpi.annulFailed', 'Не удалось аннулировать запись')}
          onSubmit={(comment, key) => kpiApi.annul(item.id, item.version, comment, key).catch((error: unknown) => {
            // Запись изменилась на сервере — перечитать, чтобы повтор ушёл с новой версией.
            if (errorStatus(error) === 409) void queryClient.invalidateQueries({ queryKey: kpiKeys.card(item.id) });
            throw error;
          })}
          onClose={(done) => {
            setAnnulling(false);
            if (done) {
              toast.success(t('bpp.kpi.annulled', 'Запись аннулирована'));
              void queryClient.invalidateQueries({ queryKey: KPI_KEY });
              void queryClient.invalidateQueries({ queryKey: ['bpp', 'history', 'bpp.kpirecord', item.id] });
            }
          }}
        />
      )}
    </div>
  );
}

export default KpiRecordPage;
