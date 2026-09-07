/**
 * Тело карточки договора.
 *
 * Поддерживает все корпоративные поля СЭД: направление, вид, тип договора,
 * № СЭД, предмет договора, куратора/менеджера, разбивку по НДС, авансы,
 * гарантийные удержания, сроки и привязку к статье бюджета.
 */

import { useRef } from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Calendar,
  FileText,
  Loader2,
  Paperclip,
  Pencil,
  ShieldCheck,
  Tag,
  Upload,
  User,
} from 'lucide-react';
import { toast } from 'sonner';

import { DetailSkeleton, Field } from '@/components/contracts/detail';
import { AgreementPaymentBreakdown } from '@/components/contracts/AgreementPaymentBreakdown';
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
import AgreementDocumentViewer from '@/components/contracts/AgreementDocumentViewer';
import ProjectLinkBadge from '@/components/contracts/ProjectLinkBadge';
import { contractsApi } from '@/api/contracts';
import { useActiveProfile } from '@/hooks/useActiveProfile';
import { ADMIN_ROLES, hasAnyRole } from '@/lib/auth/roles';
import type { AgreementStatus } from '@/types/contracts';
import { isEditableState } from '@/types/signoff';

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

const DIRECTION_LABELS: Record<string, string> = {
  expense: 'Расход',
  income: 'Поступление',
};

const KIND_LABELS: Record<string, string> = {
  works_services: 'РиУ',
  goods: 'Товары',
  services: 'Услуги',
  lease: 'Аренда',
  other: 'Прочее',
};

const TYPE_LABELS: Record<string, string> = {
  standard: 'Стандартный',
  non_standard: 'Нетиповой',
  framework: 'Рамочный',
};

interface Props {
  id: number;
  /** Тело вставлено в карточку согласования — см. `BudgetDetailView`. */
  embedded?: boolean;
}

const AgreementDetailView = ({ id: agreementId, embedded = false }: Props) => {
  const enabled = Number.isFinite(agreementId);
  const queryClient = useQueryClient();

  const { activeProfile } = useActiveProfile();
  const myId = activeProfile?.id ? Number(activeProfile.id) : null;
  const isAdmin = hasAnyRole(activeProfile?.roles ?? [], ADMIN_ROLES);

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

  const directionLabel = (val?: string) =>
    enums?.direction?.find((o) => o.value === val)?.label ?? DIRECTION_LABELS[val ?? ''] ?? val ?? 'Расход';
  const kindLabel = (val?: string) =>
    enums?.kind?.find((o) => o.value === val)?.label ?? KIND_LABELS[val ?? ''] ?? val ?? 'РиУ';
  const contractTypeLabel = (val?: string) =>
    enums?.contract_type?.find((o) => o.value === val)?.label ?? TYPE_LABELS[val ?? ''] ?? val ?? 'Стандартный';

  const invalidateAll = () => {
    queryClient.invalidateQueries({ queryKey: ['contracts'] });
    queryClient.invalidateQueries({ queryKey: ['signoff'] });
  };

  const upload = useMutation({
    mutationFn: (file: File) =>
      contractsApi.uploadAgreementFile(agreementId, file).then((r) => r.data),
    onSuccess: () => {
      toast.success('Файл договора загружен');
      invalidateAll();
    },
    onError: (err) => reportApiError(err, 'Не удалось загрузить файл'),
  });

  const canUpload =
    agreement !== undefined &&
    (isAdmin || (agreement.created_by === myId && agreement.status === 'draft'));

  const canEdit =
    agreement !== undefined &&
    isAdmin &&
    isEditableState(agreement.approval_state) &&
    !['executed', 'terminated'].includes(agreement.status);

  if (isLoading) return <DetailSkeleton />;
  if (isError || !agreement) {
    return <p className="text-sm text-destructive">Договор не найден или недоступен.</p>;
  }

  const Heading = embedded ? 'h2' : 'h1';

  // Колонка рядом с документом в режиме чтения. Здесь ровно то, что сверяют
  // с текстом договора: кто, за что, сколько и до какого числа. Остальное
  // (история согласования, оплаты) в тексте не написано, и сверять его не с
  // чем — в колонку оно не идёт.
  const documentSummary = [
    { label: 'Номер договора', value: agreement.number },
    { label: '№ СЭД', value: agreement.sed_number },
    { label: 'Контрагент', value: agreement.counterparty_name },
    { label: 'БИН/ИИН', value: agreement.counterparty_bin_iin },
    { label: 'Предмет', value: agreement.subject || agreement.name },
    { label: 'Направление', value: directionLabel(agreement.direction) },
    { label: 'Вид / тип', value: `${kindLabel(agreement.kind)} · ${contractTypeLabel(agreement.contract_type)}` },
    {
      label: 'Сумма без НДС',
      value: formatMoney(
        agreement.amount_without_vat ?? agreement.amount,
        agreement.currency,
      ),
    },
    {
      label: agreement.has_vat ? `НДС (${agreement.vat_rate}%)` : 'НДС',
      value: agreement.has_vat && agreement.vat_amount
        ? formatMoney(agreement.vat_amount, agreement.currency)
        : 'без НДС',
    },
    { label: 'Всего по договору', value: formatMoney(agreement.amount, agreement.currency) },
    {
      label: 'Аванс',
      value: agreement.has_advance
        ? `${agreement.advance_percentage || 0}%`
        : 'не предусмотрен',
    },
    {
      label: 'Гарантийное удержание',
      value: agreement.retention_rate && parseFloat(agreement.retention_rate) > 0
        ? `${agreement.retention_rate}%`
        : 'нет',
    },
    { label: 'Дата подписания', value: formatDate(agreement.signed_date) },
    {
      label: 'Срок исполнения',
      // Срок часто задан словом («уточнить»), а не датой — показываем то,
      // что заполнено, иначе в колонке будет пустая строка вместо ответа.
      value: agreement.end_date
        ? `${formatDate(agreement.start_date)} — ${formatDate(agreement.end_date)}`
        : agreement.term_comment || formatDate(agreement.start_date),
    },
    { label: 'Менеджер / куратор', value: agreement.manager_name },
    { label: 'Статья бюджета', value: `${agreement.program_name} · ${agreement.expense_item}` },
  ];

  return (
    <div className="space-y-6">
      {/* ─── Шапка ────────────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <FileText className="h-7 w-7 shrink-0 text-muted-foreground" />
            <Heading className="text-3xl font-bold">{agreement.number}</Heading>
            <Badge variant={STATUS_VARIANTS[agreement.status]}>
              {statusLabel(agreement.status)}
            </Badge>
            <Badge variant={agreement.direction === 'income' ? 'default' : 'outline'} className="capitalize">
              {directionLabel(agreement.direction)}
            </Badge>
            <Badge variant="secondary">
              {kindLabel(agreement.kind)}
            </Badge>
            <Badge variant="outline">
              {contractTypeLabel(agreement.contract_type)}
            </Badge>
            {agreement.sed_number && (
              <Badge variant="outline" className="font-mono bg-background text-xs">
                № СЭД: {agreement.sed_number}
              </Badge>
            )}
          </div>
          <p className="text-sm text-muted-foreground break-words">
            {agreement.name}
          </p>
        </div>

        {!embedded && (
          <div className="flex flex-wrap items-center gap-2">
            {canEdit && (
              <Button asChild variant="outline">
                <Link to={`/contracts/agreements/${agreement.id}/edit`}>
                  <Pencil className="mr-1.5 h-4 w-4" />
                  Редактировать
                </Link>
              </Button>
            )}
            <SubmitForApproval
              subjectType="contracts.agreement"
              subjectId={agreement.id}
              state={agreement.approval_state}
              submit={contractsApi.submitAgreement}
              invalidate={[
                ['contracts', 'agreements'],
                ['contracts', 'agreement', agreementId],
                ['contracts', 'budgets'],
                ['contracts', 'budget', agreement.budget_id],
                ['contracts', 'budget-line', agreement.budget_line_id],
              ]}
              size="default"
              showProcessLink
            />
          </div>
        )}
      </div>

      {/* ─── Финансовая сводка и НДС ───────────────────────────────────── */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center justify-between">
            <span>Финансовые условия</span>
            <span className="text-xs font-normal text-muted-foreground">
              {agreement.has_vat ? `НДС: ${agreement.vat_rate}%` : 'Без НДС'}
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          <section className="rounded-lg border bg-muted/30 p-4">
            <div className="grid gap-5 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)] lg:items-start">
              <div>
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Договор всего (с НДС)
                </p>
                <p className="mt-1 text-2xl font-bold tracking-tight tabular-nums text-foreground">
                  {formatMoney(agreement.amount, agreement.currency)}
                </p>

                <div className="mt-3 grid grid-cols-2 gap-3 pt-3 border-t text-sm">
                  <div>
                    <p className="text-xs text-muted-foreground">Договор без НДС</p>
                    <p className="mt-0.5 font-semibold tabular-nums">
                      {agreement.amount_without_vat
                        ? formatMoney(agreement.amount_without_vat, agreement.currency)
                        : formatMoney(agreement.amount, agreement.currency)}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">
                      Договор НДС {agreement.has_vat ? `(${agreement.vat_rate}%)` : ''}
                    </p>
                    <p className="mt-0.5 font-semibold tabular-nums">
                      {agreement.has_vat && agreement.vat_amount
                        ? formatMoney(agreement.vat_amount, agreement.currency)
                        : '0,00 ' + agreement.currency}
                    </p>
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4 border-t pt-4 lg:border-l lg:border-t-0 lg:pl-6 lg:pt-0">
                <div>
                  <p className="text-xs text-muted-foreground">Предоплачено</p>
                  <p className="mt-1 text-base tabular-nums">
                    {formatMoney(agreement.advance_paid_amount, agreement.currency)}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Оплачено по договору</p>
                  <p className="mt-1 text-base tabular-nums">
                    {formatMoney(agreement.contract_paid_amount, agreement.currency)}
                  </p>
                </div>
                <div className="col-span-2 flex items-end justify-between gap-4 border-t pt-3">
                  <p className="text-xs text-muted-foreground">Остаток к оплате</p>
                  <p className={`text-base font-semibold tabular-nums ${remainingTone(
                    agreement.remaining_amount,
                    agreement.amount,
                  )}`}>
                    {formatMoney(agreement.remaining_amount, agreement.currency)}
                  </p>
                </div>
              </div>
            </div>

            {/* Дополнительные параметры: аванс и гарантийное удержание */}
            <div className="mt-4 pt-3 border-t grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
              <div className="flex items-center gap-2">
                <span className="text-muted-foreground">Аванс:</span>
                <span className="font-medium">
                  {agreement.has_advance
                    ? `${agreement.advance_percentage || 0}% (план: ${formatMoney(
                        agreement.advance_amount_planned || '0',
                        agreement.currency,
                      )})`
                    : 'Не предусмотрен'}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <ShieldCheck className="h-3.5 w-3.5 text-muted-foreground" />
                <span className="text-muted-foreground">Гарантийное удержание:</span>
                <span className="font-medium">
                  {agreement.retention_rate && parseFloat(agreement.retention_rate) > 0
                    ? `${agreement.retention_rate}% (план: ${formatMoney(
                        agreement.retention_amount || '0',
                        agreement.currency,
                      )})`
                    : 'Нет'}
                </span>
              </div>
            </div>

            <AgreementPaymentBreakdown agreementId={agreement.id} />
          </section>

          {/* ─── Предмет договора ──────────────────────────────────────── */}
          {agreement.subject && (
            <div className="rounded-lg border bg-background p-4">
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground mb-1">
                Предмет договора
              </p>
              <p className="text-sm whitespace-pre-wrap leading-relaxed text-foreground">
                {agreement.subject}
              </p>
            </div>
          )}

          {/* ─── Условия и сведения ─────────────────────────────────────── */}
          <div className="grid gap-6 border-t pt-5 lg:grid-cols-[minmax(0,1.2fr)_minmax(16rem,0.8fr)]">
            <section>
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Условия и график исполнения
              </p>
              <dl className="mt-3 grid gap-x-6 gap-y-4 sm:grid-cols-2">
                <Field label="Менеджер / Куратор">
                  <span className="inline-flex items-center gap-1.5 font-medium">
                    <User className="h-3.5 w-3.5 text-muted-foreground" />
                    {agreement.manager_name || 'Не назначен'}
                  </span>
                </Field>
                <Field label="Тип оплаты">{paymentLabel(agreement.payment_type)}</Field>
                <Field label="Дата подписания">
                  {formatDate(agreement.signed_date)}
                </Field>
                <Field label="Сроки действия">
                  <span className="inline-flex items-center gap-1">
                    <Calendar className="h-3.5 w-3.5 text-muted-foreground" />
                    {formatDate(agreement.start_date)} — {formatDate(agreement.end_date)}
                  </span>
                </Field>
                {agreement.term_comment && (
                  <Field label="Срок исполнения (комментарий)" className="sm:col-span-2">
                    <span className="italic">{agreement.term_comment}</span>
                  </Field>
                )}
              </dl>
            </section>
            <section className="border-t pt-5 lg:border-l lg:border-t-0 lg:pl-6 lg:pt-0">
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Сведения о записи
              </p>
              <dl className="mt-3 space-y-4">
                <Field label="Автор">
                  {agreement.created_by !== null
                    ? `Пользователь #${agreement.created_by}`
                    : '—'}
                </Field>
                <div className="grid gap-x-6 gap-y-4 sm:grid-cols-2">
                  <Field label="Оформлен">{formatMoment(agreement.created_at)}</Field>
                  <Field label="Изменён">{formatMoment(agreement.updated_at)}</Field>
                </div>
              </dl>
            </section>
          </div>
        </CardContent>
      </Card>

      {/* ─── Источник денег и Контрагент ───────────────────────────── */}
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.4fr)_minmax(18rem,0.6fr)]">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <Tag className="h-4 w-4 text-muted-foreground" />
              Источник финансирования и статья бюджета
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <dl className="grid gap-x-6 gap-y-4 sm:grid-cols-2">
              <Field label="Проект / Администратор">
                <span className="font-medium">{agreement.administrator_name}</span>
                {/* Связь с доской задач: договор ведётся по тому же проекту,
                    что и работы. */}
                <ProjectLinkBadge
                  projectId={agreement.project_id}
                  name={agreement.administrator_name}
                  className="ml-2 align-middle"
                />
              </Field>
              <Field label="Бюджет">
                <Link
                  to={`/contracts/budgets/${agreement.budget_id}`}
                  className="hover:underline underline-offset-2 text-primary"
                >
                  Бюджет {agreement.period_year}
                </Link>
              </Field>
              <Field label="Код статьи / Программа">
                <span className="font-mono text-xs">{agreement.program_name}</span>
              </Field>
              <Field label="Статья бюджета / расходов">
                <span className="font-medium">{agreement.expense_item}</span>
              </Field>
            </dl>

            {line && (
              <div className="rounded-md border bg-muted/40 p-4 text-sm">
                <p className="mb-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  По бюджетной строке
                </p>
                <div className="flex flex-wrap justify-between gap-2">
                  <span className="text-muted-foreground">Выделено</span>
                  <span className="tabular-nums">
                    {formatMoney(line.amount, line.currency)}
                  </span>
                </div>
                <div className="flex flex-wrap justify-between gap-2">
                  <span className="text-muted-foreground">Законтрактовано</span>
                  <span className="tabular-nums">{formatAmount(line.committed)}</span>
                </div>
                <div className="mt-1 flex flex-wrap justify-between gap-2 border-t pt-1 font-medium">
                  <span>Остаток строки</span>
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
            <CardTitle className="text-base">Контрагент</CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="grid gap-x-6 gap-y-4 sm:grid-cols-2">
              <Field label="Наименование" className="sm:col-span-2">
                <Link
                  to={`/contracts/counterparties/${agreement.counterparty_id}`}
                  className="hover:underline underline-offset-2 font-medium"
                >
                  {agreement.counterparty_name}
                </Link>
              </Field>
              <Field label="БИН / ИИН">
                <span className="tabular-nums font-mono text-xs">{agreement.counterparty_bin_iin}</span>
              </Field>
            </dl>
          </CardContent>
        </Card>
      </div>

      {/* ─── Скан договора ─────────────────────────────────────────── */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-base">
            <Paperclip className="h-4 w-4" />
            Скан договора
          </CardTitle>
        </CardHeader>
        <CardContent>
          {canUpload && (
            <input
              ref={fileInput}
              type="file"
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) upload.mutate(file);
                event.target.value = '';
              }}
            />
          )}
          <div className="space-y-4">
            {agreement.file_id ? (
              <AgreementDocumentViewer
                agreementId={agreement.id}
                hasFile
                summary={documentSummary}
              />
            ) : (
              <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
                  <p className="font-medium">Файл не приложен</p>
                  <p className="mt-0.5 text-sm text-muted-foreground">
                    {canUpload
                      ? 'Загрузите скан договора, когда он будет готов.'
                      : 'Скан ещё не был добавлен к договору.'}
                  </p>
                </div>
                {canUpload && (
                  <Button
                    disabled={upload.isPending}
                    onClick={() => fileInput.current?.click()}
                  >
                    {upload.isPending ? (
                      <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                    ) : (
                      <Upload className="mr-1.5 h-4 w-4" />
                    )}
                    Загрузить
                  </Button>
                )}
              </div>
            )}

            {agreement.file_id && canUpload && (
              <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-3">
                <p className="text-xs text-muted-foreground">
                  Новый файл заменит текущий скан в карточке договора.
                </p>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={upload.isPending}
                  onClick={() => fileInput.current?.click()}
                >
                  {upload.isPending ? (
                    <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                  ) : (
                    <Upload className="mr-1.5 h-4 w-4" />
                  )}
                  Заменить
                </Button>
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {!embedded && (
        <SubjectProcesses subjectType="contracts.agreement" subjectId={agreement.id} />
      )}
    </div>
  );
};

export default AgreementDetailView;
