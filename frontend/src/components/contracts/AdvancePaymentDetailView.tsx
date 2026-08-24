import { useQuery } from '@tanstack/react-query';
import { FileCheck2 } from 'lucide-react';

import { contractsApi } from '@/api/contracts';
import { DetailSkeleton, Field } from '@/components/contracts/detail';
import { formatMoment, formatMoney } from '@/components/contracts/format';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

interface Props {
  id: number;
  embedded?: boolean;
}

const approvalLabel: Record<string, string> = {
  draft: 'Черновик',
  pending: 'На согласовании',
  approved: 'Согласовано',
  rejected: 'Отклонено',
  rework: 'На доработке',
};

const statusLabel: Record<string, string> = {
  draft: 'Черновик',
  on_review: 'На согласовании',
  awaiting_accounting: 'Ожидает бухгалтерию',
  closed: 'Закрыта',
};

/** Read-only advance-payment card used inside a Signoff process. */
export default function AdvancePaymentDetailView({ id }: Props) {
  const { data: payment, isLoading, isError } = useQuery({
    queryKey: ['contracts', 'advance-payment', id],
    queryFn: () => contractsApi.getAdvancePayment(id).then((response) => response.data),
    enabled: Number.isFinite(id),
  });

  if (isLoading) return <DetailSkeleton />;
  if (isError || !payment) {
    return <p className="text-sm text-destructive">Предоплата не найдена или недоступна.</p>;
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex flex-wrap items-center gap-2 text-base">
          <FileCheck2 className="h-4 w-4" />
          Предоплата
          <Badge variant={payment.status === 'closed' ? 'default' : 'secondary'}>
            {statusLabel[payment.status] ?? payment.status}
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        <section className="rounded-lg border bg-muted/30 p-4">
          <p className="text-sm text-muted-foreground">Сумма предоплаты</p>
          <p className="mt-1 text-2xl font-semibold tracking-tight tabular-nums">
            {formatMoney(payment.amount, payment.currency)}
          </p>
        </section>
        <section>
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            По договору
          </p>
          <dl className="mt-3 grid gap-x-6 gap-y-4 sm:grid-cols-2">
            <Field label="Договор">
              {payment.agreement_number} — {payment.agreement_name}
            </Field>
            <Field label="Контрагент">{payment.counterparty_name}</Field>
          </dl>
        </section>
        <section className="border-t pt-5">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Сведения о записи
          </p>
          <dl className="mt-3 grid gap-x-6 gap-y-4 sm:grid-cols-2">
            <Field label="Согласование">
              {approvalLabel[payment.approval_state] ?? payment.approval_state}
            </Field>
            <Field label="Создана">{formatMoment(payment.created_at)}</Field>
            {payment.status === 'closed' && (
              <Field label="Проводка">{payment.posting_number || '—'}</Field>
            )}
          </dl>
        </section>
      </CardContent>
    </Card>
  );
}
