/**
 * Тело карточки счёта на оплату (без договора).
 *
 * По образцу `AgreementDetailView`, но проще: у счёта нет номера, типа
 * оплаты, даты подписания и — в первой фазе — согласования, поэтому здесь нет
 * ни блока отправки на согласование (`SubmitForApproval`), ни истории
 * процессов. Остаются две операции над уже существующим счётом:
 *
 * - **смена статуса.** Переходы разрешает бэкенд по
 *   `invoice_service.ALLOWED_TRANSITIONS`, таблица приходит с `/enums`
 *   (`invoice_transitions`) — своей копии здесь нет. Операция админская.
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

import { DetailSkeleton, Field, FieldGrid } from '@/components/contracts/detail';
import {
  formatAmount,
  formatMoment,
  formatMoney,
  remainingTone,
} from '@/components/contracts/format';
import { reportApiError } from '@/components/signoff/apiError';
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
import type { InvoiceStatus } from '@/types/contracts';

const ADMIN_ROLES = ['admin', 'superuser', 'staff'] as const;

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
  const myId = activeProfile?.id ? Number(activeProfile.id) : null;
  const isAdmin = hasAnyRole(activeProfile?.roles ?? [], ADMIN_ROLES);

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

  // Строка бюджета — ради остатка (контекст, а не лимит: счёт бюджет не
  // занимает). Спрашивается именно СТРОКА — деньги выделены программе.
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
  // своего черновика либо администратор. Кнопка их лишь отражает.
  const canEdit = canUpload;

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

        {!embedded && canEdit && (
          <Button asChild variant="outline">
            <Link to={`/contracts/invoices/${invoice.id}/edit`}>
              <Pencil className="mr-1.5 h-4 w-4" />
              Редактировать
            </Link>
          </Button>
        )}
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Счёт</CardTitle>
        </CardHeader>
        <CardContent>
          <FieldGrid>
            <Field label="Сумма">
              <span className="text-lg font-semibold tabular-nums">
                {formatMoney(invoice.amount, invoice.currency)}
              </span>
            </Field>
            <Field label="Автор">
              {invoice.created_by !== null
                ? `Пользователь #${invoice.created_by}`
                : '—'}
            </Field>
            <Field label="Выписан">{formatMoment(invoice.created_at)}</Field>
            {invoice.note && (
              <Field label="Пояснение" className="sm:col-span-2">
                <span className="whitespace-pre-wrap">{invoice.note}</span>
              </Field>
            )}
            <Field label="Изменён">{formatMoment(invoice.updated_at)}</Field>
          </FieldGrid>
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
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
                  Счёт без договора остаток не уменьшает — показан для справки.
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
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Скан счёта на оплату</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-3">
          {invoice.file_id ? (
            <>
              <span className="inline-flex items-center gap-1.5 text-sm text-muted-foreground">
                <Paperclip className="h-4 w-4" />
                Файл приложен
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
                Открыть
              </Button>
            </>
          ) : (
            <span className="text-sm text-muted-foreground">Файл не приложен.</span>
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
                  // Сброс — иначе повторный выбор ТОГО ЖЕ файла не даст события
                  // change и загрузка молча не произойдёт.
                  event.target.value = '';
                }}
              />
              <Button
                variant={invoice.file_id ? 'ghost' : 'default'}
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
              {invoice.file_id && (
                <span className="text-xs text-muted-foreground">
                  Замена вытеснит текущий файл из карточки.
                </span>
              )}
            </>
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
    </div>
  );
};

export default InvoiceDetailView;
