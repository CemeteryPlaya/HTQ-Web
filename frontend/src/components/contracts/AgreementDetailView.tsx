/**
 * Тело карточки договора.
 *
 * Отделено от страницы (`pages/contracts/AgreementDetail`) ради карточки
 * согласования: `pages/signoff/ProcessDetail` показывает то же тело, чтобы
 * согласующий читал документ, не выходя из своего раздела. Рамку выбирает
 * тот, кто рисует.
 *
 * Здесь же живут две операции, у которых больше нигде в интерфейсе места
 * нет, потому что обе относятся к УЖЕ существующему договору:
 *
 * - **смена статуса.** Переходы разрешает бэкенд по
 *   `agreement_service.ALLOWED_TRANSITIONS`, и таблица приходит с `/enums` —
 *   своей копии здесь нет и быть не должно, иначе она разъедется с сервером
 *   при первой же правке. Операция админская (`api_view(admin=True)`), и
 *   это не дубль согласования: штатно статус двигает маршрут
 *   (`draft → on_review → approved`), а руками — исправляют то, чего
 *   маршрут не покрывает («подписан», «исполнен», «расторгнут»).
 * - **скан договора.** Загрузить может автор, пока договор черновик, либо
 *   администратор всегда — те же условия, что проверяет бэкенд
 *   (`views.AgreementFileView`). Повторная загрузка ЗАМЕЩАЕТ файл, поэтому
 *   автору она и закрыта после отправки: согласующие не должны оказаться
 *   одобрившими не тот документ, который в итоге лежит в карточке.
 *
 * Обе остаются видимы и во встроенном виде: скан согласующему как раз и
 * нужен, а смена статуса и так закрыта админской проверкой на бэкенде.
 */

import { useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Download,
  FileText,
  Loader2,
  Paperclip,
  Upload,
} from 'lucide-react';
import { toast } from 'sonner';

import { DetailSkeleton, Field, FieldGrid } from '@/components/contracts/detail';
import {
  formatAmount,
  formatDate,
  formatMoment,
  formatMoney,
  remainingTone,
} from '@/components/contracts/format';
import { reportApiError } from '@/lib/apiError';
import { SubmitForApproval } from '@/components/signoff/SubmitForApproval';
import { SubjectProcesses } from '@/components/signoff/SubjectProcesses';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { contractsApi } from '@/api/contracts';
import { useActiveProfile } from '@/hooks/useActiveProfile';
import { hasAnyRole } from '@/lib/auth/roles';
import type { AgreementStatus } from '@/types/contracts';
import { useTranslation } from 'react-i18next';

const ADMIN_ROLES = ['admin', 'superuser', 'staff'] as const;

const STATUS_VARIANTS: Record<
  AgreementStatus,
  'default' | 'secondary' | 'outline' | 'destructive'
> = {
  draft: 'outline',
  on_review: 'secondary',
  approved: 'secondary',
  signed: 'default',
  executed: 'default',
  terminated: 'destructive',
};

interface Props {
  id: number;
  /** Тело вставлено в карточку согласования — см. `BudgetDetailView`. */
  embedded?: boolean;
}

const AgreementDetailView = ({ id: agreementId, embedded = false }: Props) => {
  const { t } = useTranslation();
  const enabled = Number.isFinite(agreementId);
  const queryClient = useQueryClient();

  const { activeProfile } = useActiveProfile();
  const myId = activeProfile?.id ? Number(activeProfile.id) : null;
  const isAdmin = hasAnyRole(activeProfile?.roles ?? [], ADMIN_ROLES);

  const [nextStatus, setNextStatus] = useState('');
  const fileInput = useRef<HTMLInputElement>(null);

  const {
    data: agreement,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ['contracts', 'agreement', agreementId],
    queryFn: () => contractsApi.getAgreement(agreementId).then((r) => r.data),
    enabled,
  });

  const { data: enums } = useQuery({
    queryKey: ['contracts', 'enums'],
    queryFn: () => contractsApi.getEnums().then((r) => r.data),
  });

  // Строка бюджета — ради остатка: он показывает, сколько ещё можно
  // потратить с того же источника, и считается бэкендом. Спрашивается
  // именно СТРОКА, а не бюджет целиком: лимит договора — это лимит его
  // программы, и свободные деньги соседней программы к нему отношения не
  // имеют (`budget_calc.check_capacity`).
  const { data: line } = useQuery({
    queryKey: ['contracts', 'budget-line', agreement?.budget_line_id],
    queryFn: () =>
      contractsApi.getBudgetLine(agreement!.budget_line_id).then((r) => r.data),
    enabled: agreement !== undefined,
  });

  const statusLabel = (value: AgreementStatus) =>
    enums?.agreement_status.find((option) => option.value === value)?.label ?? value;
  const paymentLabel = (value: string) =>
    enums?.payment_type.find((option) => option.value === value)?.label ?? value;

  /** Всё, что должно перечитаться после действия над договором. Остаток
   *  бюджета — тоже: статус договора решает, занимает ли он деньги. */
  const invalidateAll = () => {
    queryClient.invalidateQueries({ queryKey: ['contracts'] });
    queryClient.invalidateQueries({ queryKey: ['signoff'] });
  };

  const changeStatus = useMutation({
    mutationFn: () =>
      contractsApi
        .changeAgreementStatus(agreementId, nextStatus as AgreementStatus)
        .then((r) => r.data),
    onSuccess: (row) => {
      setNextStatus('');
      toast.success(t('contracts.agreement.statusChanged', { status: statusLabel(row.status) }));
      invalidateAll();
    },
    // 409 — переход запрещён таблицей или сумма не помещается в остаток
    // (переход в занимающий бюджет статус лимит перепроверяет).
    onError: (err) => reportApiError(err, t('contracts.agreement.statusError')),
  });

  const upload = useMutation({
    mutationFn: (file: File) =>
      contractsApi.uploadAgreementFile(agreementId, file).then((r) => r.data),
    onSuccess: () => {
      toast.success(t('contracts.agreement.fileUploaded'));
      invalidateAll();
    },
    // 403 — «заменить скан может только администратор» после отправки.
    onError: (err) => reportApiError(err, t('contracts.agreement.uploadError')),
  });

  /** Ссылка подписанная и живёт недолго, поэтому запрашивается по клику, а
   *  не заранее вместе с карточкой. */
  const download = useMutation({
    mutationFn: () =>
      contractsApi.getAgreementFileUrl(agreementId).then((r) => r.data.url),
    onSuccess: (url) => window.open(url, '_blank', 'noopener,noreferrer'),
    onError: (err) => reportApiError(err, t('contracts.agreement.linkError')),
  });

  const transitions = agreement
    ? enums?.transitions?.[agreement.status] ?? []
    : [];
  const canUpload =
    agreement !== undefined
    && (isAdmin || (agreement.created_by === myId && agreement.status === 'draft'));

  if (isLoading) return <DetailSkeleton />;
  if (isError || !agreement) {
    return <p className="text-sm text-destructive">{t('contracts.agreement.notFound')}</p>;
  }

  const Heading = embedded ? 'h2' : 'h1';

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-3">
            <FileText className="h-7 w-7 shrink-0 text-muted-foreground" />
            <Heading className="text-3xl font-bold">{agreement.number}</Heading>
            <Badge variant={STATUS_VARIANTS[agreement.status]}>
              {statusLabel(agreement.status)}
            </Badge>
          </div>
          <p className="mt-1 text-sm text-muted-foreground break-words">
            {agreement.name}
          </p>
        </div>

        {!embedded && (
          <SubmitForApproval
            subjectType="contracts.agreement"
            subjectId={agreement.id}
            state={agreement.approval_state}
            submit={contractsApi.submitAgreement}
            // Отправка переводит договор в on_review, а он уже занимает
            // бюджет — остаток строки меняется тем же действием.
            invalidate={[
              ['contracts', 'agreements'],
              ['contracts', 'agreement', agreementId],
              ['contracts', 'budgets'],
              ['contracts', 'budget', agreement.budget_id],
              ['contracts', 'budget-line', agreement.budget_line_id],
            ]}
            size="default"
            // Карточка объекта — единственное место, где ссылка на
            // согласование нужна и у решённого объекта: там кнопка
            // «Вернуть на доработку», без которой он заперт навсегда.
            showProcessLink
          />
        )}
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">{t('contracts.agreement.title')}</CardTitle>
        </CardHeader>
        <CardContent>
          <FieldGrid>
            <Field label={t('contracts.columns.amount')}>
              <span className="text-lg font-semibold tabular-nums">
                {formatMoney(agreement.amount, agreement.currency)}
              </span>
            </Field>
            <Field label={t('contracts.columns.paymentType')}>{paymentLabel(agreement.payment_type)}</Field>
            <Field label={t('contracts.columns.signedAt')}>
              {formatDate(agreement.signed_date)}
            </Field>
            <Field label={t('contracts.columns.title')} className="sm:col-span-2">
              {agreement.name}
            </Field>
            <Field label={t('contracts.columns.author')}>
              {agreement.created_by !== null
                ? t('signoff.userNumber', { id: agreement.created_by })
                : '—'}
            </Field>
            <Field label={t('contracts.columns.issuedAt')}>{formatMoment(agreement.created_at)}</Field>
            <Field label={t('contracts.updatedAt')}>{formatMoment(agreement.updated_at)}</Field>
          </FieldGrid>
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">{t('contracts.agreement.moneySource')}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <dl className="grid gap-x-6 gap-y-4 sm:grid-cols-2">
              {/* Ссылка ведёт на БЮДЖЕТ, а не на строку: своей страницы
                  у строки нет, да и смотреть её в отрыве от соседних
                  программ незачем. */}
              <Field label={t('contracts.columns.budget')}>
                <Link
                  to={`/contracts/budgets/${agreement.budget_id}`}
                  className="hover:underline underline-offset-2"
                >
                  {t('contracts.budget.titleYear', { year: agreement.period_year })}
                </Link>
              </Field>
              <Field label={t('contracts.columns.administrator')}>{agreement.administrator_name}</Field>
              <Field label={t('contracts.columns.programme')}>{agreement.program_name}</Field>
              <Field label={t('contracts.columns.expenseItem')}>{agreement.expense_item}</Field>
            </dl>
            {line && (
              <div className="rounded-md border bg-muted/40 p-4 text-sm">
                <div className="flex flex-wrap justify-between gap-2">
                  <span className="text-muted-foreground">{t('contracts.columns.allocated')}</span>
                  <span className="tabular-nums">
                    {formatMoney(line.amount, line.currency)}
                  </span>
                </div>
                <div className="flex flex-wrap justify-between gap-2">
                  <span className="text-muted-foreground">{t('contracts.columns.contracted')}</span>
                  <span className="tabular-nums">{formatAmount(line.committed)}</span>
                </div>
                <div className="mt-1 flex flex-wrap justify-between gap-2 border-t pt-1 font-medium">
                  <span>{t('contracts.agreement.lineRemaining')}</span>
                  <span
                    className={`tabular-nums ${remainingTone(
                      line.remaining,
                      line.amount,
                    )}`}
                  >
                    {formatAmount(line.remaining)}
                  </span>
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">{t('contracts.columns.counterparty')}</CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="grid gap-x-6 gap-y-4 sm:grid-cols-2">
              <Field label={t('contracts.columns.title')} className="sm:col-span-2">
                <Link
                  to={`/contracts/counterparties/${agreement.counterparty_id}`}
                  className="hover:underline underline-offset-2"
                >
                  {agreement.counterparty_name}
                </Link>
              </Field>
              <Field label={t('contracts.counterparty.bin')}>
                <span className="tabular-nums">{agreement.counterparty_bin_iin}</span>
              </Field>
            </dl>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">{t('contracts.agreement.scan')}</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-3">
          {agreement.file_id ? (
            <>
              <span className="inline-flex items-center gap-1.5 text-sm text-muted-foreground">
                <Paperclip className="h-4 w-4" />
                {t('contracts.agreement.fileAttached')}
              </span>
              <Button
                variant="outline"
                disabled={download.isPending}
                onClick={() => download.mutate()}
              >
                {download.isPending ? (
                  <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                ) : (
                  <Download className="mr-1.5 h-4 w-4" />
                )}
                {t('common.open')}
              </Button>
            </>
          ) : (
            <span className="text-sm text-muted-foreground">{t('contracts.agreement.noFile')}</span>
          )}

          {canUpload && (
            <>
              <input
                ref={fileInput}
                type="file"
                className="hidden"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) upload.mutate(file);
                  // Сброс — иначе повторный выбор ТОГО ЖЕ файла не даст
                  // события change и загрузка молча не произойдёт.
                  event.target.value = '';
                }}
              />
              <Button
                variant={agreement.file_id ? 'ghost' : 'default'}
                disabled={upload.isPending}
                onClick={() => fileInput.current?.click()}
              >
                {upload.isPending ? (
                  <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                ) : (
                  <Upload className="mr-1.5 h-4 w-4" />
                )}
                {agreement.file_id ? t('contracts.agreement.replaceFile') : t('contracts.agreement.uploadFile')}
              </Button>
              {agreement.file_id && (
                <span className="text-xs text-muted-foreground">
                  {t('contracts.agreement.replaceHint')}
                </span>
              )}
            </>
          )}
        </CardContent>
      </Card>

      {isAdmin && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">{t('contracts.agreement.statusChange')}</CardTitle>
          </CardHeader>
          <CardContent>
            {transitions.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                {t('contracts.agreement.terminalStatus', { status: statusLabel(agreement.status) })}
              </p>
            ) : (
              <div className="flex flex-wrap items-center gap-3">
                <Select value={nextStatus} onValueChange={setNextStatus}>
                  <SelectTrigger className="w-56">
                    <SelectValue placeholder={t('contracts.agreement.newStatus')} />
                  </SelectTrigger>
                  <SelectContent>
                    {transitions.map((value) => (
                      <SelectItem key={value} value={value}>
                        {statusLabel(value)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button
                  disabled={!nextStatus || changeStatus.isPending}
                  onClick={() => changeStatus.mutate()}
                >
                  {changeStatus.isPending && (
                    <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                  )}
                  {t('contracts.applyStatus')}
                </Button>
                <p className="w-full text-xs text-muted-foreground">
                  {t('contracts.agreement.statusHint')}
                </p>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {!embedded && (
        <SubjectProcesses subjectType="contracts.agreement" subjectId={agreement.id} />
      )}
    </div>
  );
};

export default AgreementDetailView;
