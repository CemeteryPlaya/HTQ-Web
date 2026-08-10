import { FileCheck2 } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';

import { contractsApi } from '@/api/contracts';
import { DetailSkeleton, Field, FieldGrid } from '@/components/contracts/detail';
import { formatAmount, formatMoment } from '@/components/contracts/format';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

interface Props {
  id: number;
  embedded?: boolean;
}

/** Read-only advance-payment card used inside a Signoff process. */
export default function AdvancePaymentDetailView({ id }: Props) {
  const { data: payment, isLoading, isError } = useQuery({
    queryKey: ['contracts', 'advance-payment', id],
    queryFn: () => contractsApi.getAdvancePayment(id).then((response) => response.data),
    enabled: Number.isFinite(id),
  });

  if (isLoading) return <DetailSkeleton />;
  if (isError || !payment) {
    return (
      <p className="text-sm text-destructive">
        Предоплата не найдена или недоступна.
      </p>
    );
  }

  const statusLabel = {
    draft: 'Черновик',
    on_review: 'На согласовании',
    awaiting_accounting: 'Ожидает бухгалтерию',
    closed: 'Закрыта',
  }[payment.status];

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex flex-wrap items-center gap-2 text-base">
          <FileCheck2 className="h-4 w-4" />
          Предоплата
          <Badge variant={payment.status === 'closed' ? 'default' : 'secondary'}>
            {statusLabel}
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <FieldGrid>
          <Field label="Договор">
            {payment.agreement_number} — {payment.agreement_name}
          </Field>
          <Field label="Контрагент">{payment.counterparty_name}</Field>
          <Field label="Сумма">
            {formatAmount(payment.amount)} {payment.currency}
          </Field>
          <Field label="Согласование">{payment.approval_state}</Field>
          <Field label="Создана">{formatMoment(payment.created_at)}</Field>
          {payment.status === 'closed' && (
            <Field label="Проводка">{payment.posting_number || '—'}</Field>
          )}
        </FieldGrid>
      </CardContent>
    </Card>
  );
}
