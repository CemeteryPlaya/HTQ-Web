import { useQuery } from '@tanstack/react-query';
import { FileText } from 'lucide-react';

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

/** Compact contract-payment card for the Signoff process page. */
export default function ContractPaymentDetailView({ id }: Props) {
  const { data: payment, isLoading, isError } = useQuery({
    queryKey: ['contracts', 'contract-payment', id],
    queryFn: () => contractsApi.getContractPayment(id).then((response) => response.data),
    enabled: Number.isFinite(id),
  });

  if (isLoading) return <DetailSkeleton />;
  if (isError || !payment) {
    return <p className="text-sm text-destructive">Оплата по договору не найдена или недоступна.</p>;
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex flex-wrap items-center gap-2 text-base">
          <FileText className="h-4 w-4" />
          Оплата по договору
          <Badge variant={payment.status === 'closed' ? 'default' : 'secondary'}>
            {statusLabel[payment.status] ?? payment.status}
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        <section className="rounded-lg border bg-muted/30 p-4">
          <p className="text-sm text-muted-foreground">Сумма оплаты</p>
          <p className="mt-1 text-2xl font-semibold tracking-tight tabular-nums">
            {formatMoney(payment.amount, payment.currency)}
          </p>
        </section>
        <section>
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            По договору
          </p>
          <dl className="mt-3 grid gap-x-6 gap-y-4 sm:grid-cols-2">
            <Field label="Администратор">{payment.administrator_name}</Field>
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
          </dl>
        </section>
      </CardContent>
    </Card>
  );
}
