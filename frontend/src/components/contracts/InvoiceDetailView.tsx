/**
 * Тело карточки счёта на оплату (без договора).
 *
 * По образцу `AgreementDetailView`, но проще: у счёта нет номера, типа
 * оплаты и даты подписания. Согласование — то же, что у договора:
 *
 * - **отправка на согласование** (`SubmitForApproval`) и **история
 *   процессов** (`SubjectProcesses`) — ровно как у договора. Отличие лишь на
 *   бэкенде: скан обязателен уже на отправке, поэтому по счёту без файла
 *   `/submit` ответит 409 (текст показывает `reportApiError`).
 * - **смена статуса.** Переходы разрешает бэкенд по
 *   `invoice_service.ALLOWED_TRANSITIONS`, таблица приходит с `/enums`
 *   (`invoice_transitions`) — своей копии здесь нет. Пока идёт согласование,
 *   ручной перевод бэкенд запирает (`enforce_approval_lock`). Операция
 *   админская.
 * - **правка** доступна только пока счёт правится по оси согласования
 *   (`isEditableState`) — иначе кнопка ведёт на страницу, где сохранение
 *   упрётся в 409 `SubjectLocked`.
 * - **скан счёта.** Загрузить может автор, пока счёт черновик, либо
 *   администратор всегда — те же условия, что проверяет бэкенд
 *   (`views.InvoiceFileView`). Повторная загрузка ЗАМЕЩАЕТ файл.
 *
 * `embedded` заготовлен на будущее (карточка согласования), сейчас
 * страница всегда рисует полный вид.
 */

import { useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Download, Loader2, Paperclip, Pencil, Receipt, Upload } from 'lucide-react';
import { toast } from 'sonner';

import { DetailSkeleton, Field } from '@/components/contracts/detail';
import {
  formatAmount,
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
import { usePermissions } from '@/hooks/usePermissions';
import type { InvoiceStatus } from '@/types/contracts';
import { isEditableState } from '@/types/signoff';


const STATUS_VARIANTS: Record<
  InvoiceStatus,
  'default' | 'secondary' | 'outline' | 'destructive'
> = {
  draft: 'outline',
  on_review: 'secondary',
  approved: 'secondary',
  paid: 'default',
  cancelled: 'destructive',
};

interface Props {
  id: number;
  /** Заготовка на встраивание в карточку согласования (пока не используется). */
  embedded?: boolean;
}

const InvoiceDetailView = ({ id: invoiceId, embedded = false }: Props) => {
  const enabled = Number.isFinite(invoiceId);
  const queryClient = useQueryClient();

  const { activeProfile } = useActiveProfile();
  const permissions = usePermissions();
  const myId = activeProfile?.id ? Number(activeProfile.id) : null;
  const isAdmin = permissions.atLeast('contracts', 'admin');

  const [nextStatus, setNextStatus] = useState('');
  const fileInput = useRef<HTMLInputElement>(null);

  const {
    data: invoice,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ['contracts', 'invoice', invoiceId],
    queryFn: () => contractsApi.getInvoice(invoiceId).then((r) => r.data),
    enabled,
  });

  const { data: enums } = useQuery({
    queryKey: ['contracts', 'enums'],
    queryFn: () => contractsApi.getEnums().then((r) => r.data),
  });

  // Строка бюджета показывает остаток конкретной программы. Счёт уменьшит
  // его после согласования, поэтому проверять нужно именно СТРОКУ.
  const { data: line } = useQuery({
    queryKey: ['contracts', 'budget-line', invoice?.budget_line_id],
    queryFn: () =>
      contractsApi.getBudgetLine(invoice!.budget_line_id).then((r) => r.data),
    enabled: invoice !== undefined,
  });

  const statusLabel = (value: InvoiceStatus) =>
    enums?.invoice_status.find((option) => option.value === value)?.label ?? value;

  const invalidateAll = () => {
    queryClient.invalidateQueries({ queryKey: ['contracts'] });
  };

  const changeStatus = useMutation({
    mutationFn: () =>
      contractsApi
        .changeInvoiceStatus(invoiceId, nextStatus as InvoiceStatus)
        .then((r) => r.data),
    onSuccess: (row) => {
      setNextStatus('');
      toast.success(`Статус изменён: ${statusLabel(row.status)}`);
      invalidateAll();
    },
    // 409 — переход запрещён таблицей.
    onError: (err) => reportApiError(err, 'Не удалось изменить статус'),
  });

  const upload = useMutation({
    mutationFn: (file: File) =>
      contractsApi.uploadInvoiceFile(invoiceId, file).then((r) => r.data),
    onSuccess: () => {
      toast.success('Скан счёта загружен');
      invalidateAll();
    },
    // 403 — «заменить скан может только администратор» после черновика.
    onError: (err) => reportApiError(err, 'Не удалось загрузить файл'),
  });

  const download = useMutation({
    mutationFn: () =>
      contractsApi.getInvoiceFileUrl(invoiceId).then((r) => r.data.url),
    onSuccess: (url) => window.open(url, '_blank', 'noopener,noreferrer'),
    onError: (err) => reportApiError(err, 'Не удалось получить ссылку на файл'),
  });

  const transitions = invoice
    ? enums?.invoice_transitions?.[invoice.status] ?? []
    : [];
  const canUpload =
    invoice !== undefined
    && (isAdmin || (invoice.created_by === myId && invoice.status === 'draft'));
  // Правка — по тем же правам, что бэкенд (`InvoiceDetailView.patch`): автор
  // своего черновика либо администратор. Плюс ось согласования: пока счёт
  // заперт (`pending`/`approved`/`rejected`), править нельзя даже
  // администратору — `assert_editable` ответит 409, кнопку гасим заранее.
  const canEdit =
    invoice !== undefined
    && (isAdmin || (invoice.created_by === myId && invoice.status === 'draft'))
    && isEditableState(invoice.approval_state);

  if (isLoading) return <DetailSkeleton />;
  if (isError || !invoice) {
    return <p className="text-sm text-destructive">Счёт не найден или недоступен.</p>;
  }

  const Heading = embedded ? 'h2' : 'h1';

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-3">
            <Receipt className="h-7 w-7 shrink-0 text-muted-foreground" />
            <Heading className="text-3xl font-bold break-words">{invoice.name}</Heading>
            <Badge variant={STATUS_VARIANTS[invoice.status]}>
              {statusLabel(invoice.status)}
            </Badge>
          </div>
        </div>

        {!embedded && (
          <div className="flex flex-wrap items-center gap-2">
            {canEdit && (
              <Button asChild variant="outline">
                <Link to={`/contracts/invoices/${invoice.id}/edit`}>
                  <Pencil className="mr-1.5 h-4 w-4" />
                  Редактировать
                </Link>
              </Button>
            )}
            <SubmitForApproval
              subjectType="contracts.invoice"
              subjectId={invoice.id}
              state={invoice.approval_state}
              submit={contractsApi.submitInvoice}
              // На момент отправки счёт ещё не уменьшает остаток; это случится
              // после одобрения, когда откроется карточка согласования.
              invalidate={[
                ['contracts', 'invoices'],
                ['contracts', 'invoice', invoiceId],
              ]}
              size="default"
              // На карточке объекта ссылка нужна и у решённого счёта: там
              // кнопка «Вернуть на доработку», без которой он заперт навсегда.
              showProcessLink
            />
          </div>
        )}
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Счёт без договора</CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          <section className="rounded-lg border bg-muted/30 p-4">
            <p className="text-sm text-muted-foreground">Сумма счёта</p>
            <p className="mt-1 text-2xl font-semibold tracking-tight tabular-nums">
              {formatMoney(invoice.amount, invoice.currency)}
            </p>
          </section>
          {invoice.note && (
            <section className="border-t pt-5">
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Пояснение
              </p>
              <p className="mt-3 whitespace-pre-wrap text-sm">{invoice.note}</p>
            </section>
          )}
          <section className="border-t pt-5">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Сведения о записи
            </p>
            <dl className="mt-3 grid gap-x-6 gap-y-4 sm:grid-cols-3">
              <Field label="Автор">
                {invoice.created_by !== null
                  ? `Пользователь #${invoice.created_by}`
                  : '—'}
              </Field>
              <Field label="Выписан">{formatMoment(invoice.created_at)}</Field>
              <Field label="Изменён">{formatMoment(invoice.updated_at)}</Field>
            </dl>
          </section>
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.4fr)_minmax(18rem,0.6fr)]">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Источник денег</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <dl className="grid gap-x-6 gap-y-4 sm:grid-cols-2">
              <Field label="Бюджет">
                <Link
                  to={`/contracts/budgets/${invoice.budget_id}`}
                  className="hover:underline underline-offset-2"
                >
                  Бюджет {invoice.period_year}
                </Link>
              </Field>
              <Field label="Администратор">{invoice.administrator_name}</Field>
              <Field label="Программа">{invoice.program_name}</Field>
              <Field label="Статья расходов">{invoice.expense_item}</Field>
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
                <p className="text-xs text-muted-foreground mt-2">
                  Сумма проверяется по этому остатку, а уменьшится он после
                  согласования счёта.
                </p>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Поставщик</CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="grid gap-x-6 gap-y-4 sm:grid-cols-2">
              <Field label="Наименование" className="sm:col-span-2">
                <Link
                  to={`/contracts/counterparties/${invoice.counterparty_id}`}
                  className="hover:underline underline-offset-2"
                >
                  {invoice.counterparty_name}
                </Link>
              </Field>
              <Field label="БИН / ИИН">
                <span className="tabular-nums">{invoice.counterparty_bin_iin}</span>
              </Field>
            </dl>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-base">
            <Paperclip className="h-4 w-4" />
            Скан счёта на оплату
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
                // Сброс — иначе повторный выбор ТОГО ЖЕ файла не даст события
                // change и загрузка молча не произойдёт.
                event.target.value = '';
              }}
            />
          )}
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <p className="font-medium">
                {invoice.file_id ? 'Файл приложен' : 'Файл не приложен'}
              </p>
              <p className="mt-0.5 text-sm text-muted-foreground">
                {invoice.file_id
                  ? 'Откройте скан или загрузите обновлённую версию.'
                  : canUpload
                    ? 'Загрузите скан счёта, когда он будет готов.'
                    : 'Скан ещё не был добавлен к счёту.'}
              </p>
            </div>
            <div className="flex shrink-0 flex-wrap gap-2">
              {invoice.file_id && (
                <Button disabled={download.isPending} onClick={() => download.mutate()}>
                  {download.isPending ? (
                    <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                  ) : (
                    <Download className="mr-1.5 h-4 w-4" />
                  )}
                  Открыть
                </Button>
              )}
              {canUpload && (
                <Button
                  variant={invoice.file_id ? 'outline' : 'default'}
                  disabled={upload.isPending}
                  onClick={() => fileInput.current?.click()}
                >
                  {upload.isPending ? (
                    <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                  ) : (
                    <Upload className="mr-1.5 h-4 w-4" />
                  )}
                  {invoice.file_id ? 'Заменить' : 'Загрузить'}
                </Button>
              )}
            </div>
          </div>
          {invoice.file_id && canUpload && (
            <p className="mt-4 border-t pt-3 text-xs text-muted-foreground">
              Новый файл заменит текущий скан в карточке счёта.
            </p>
          )}
        </CardContent>
      </Card>

      {isAdmin && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Смена статуса</CardTitle>
          </CardHeader>
          <CardContent>
            {transitions.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Из статуса «{statusLabel(invoice.status)}» переходов нет — он
                терминальный.
              </p>
            ) : (
              <div className="flex flex-wrap items-center gap-3">
                <Select value={nextStatus} onValueChange={setNextStatus}>
                  <SelectTrigger className="w-56">
                    <SelectValue placeholder="Новый статус" />
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
                  Применить
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {!embedded && (
        <SubjectProcesses subjectType="contracts.invoice" subjectId={invoice.id} />
      )}
    </div>
  );
};

export default InvoiceDetailView;
