import { useQuery } from '@tanstack/react-query';
import { FileText } from 'lucide-react';

import { contractsApi } from '@/api/contracts';
import { DetailSkeleton, Field, FieldGrid } from '@/components/contracts/detail';
import { formatAmount, formatMoment } from '@/components/contracts/format';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

interface Props { id: number; embedded?: boolean }

/** Compact contract-payment card for the Signoff process page. */
export default function ContractPaymentDetailView({ id }: Props) {
  const { data: payment, isLoading, isError } = useQuery({
    queryKey: ['contracts', 'contract-payment', id],
    queryFn: () => contractsApi.getContractPayment(id).then(r => r.data),
  });
  if (isLoading) return <DetailSkeleton />;
  if (isError || !payment) return <p className="text-sm text-destructive">Оплата по договору не найдена или недоступна.</p>;
  const status = { draft: 'Черновик', on_review: 'На согласовании', awaiting_accounting: 'Ожидает бухгалтерию', closed: 'Закрыт' }[payment.status];
  return <Card><CardHeader className="pb-3"><CardTitle className="flex items-center gap-2 text-base"><FileText className="h-4 w-4" />Оплата по договору <Badge variant={payment.status === 'closed' ? 'default' : 'secondary'}>{status}</Badge></CardTitle></CardHeader><CardContent><FieldGrid><Field label="Администратор">{payment.administrator_name}</Field><Field label="Договор">{payment.agreement_number} — {payment.agreement_name}</Field><Field label="Контрагент">{payment.counterparty_name}</Field><Field label="Сумма">{formatAmount(payment.amount)} {payment.currency}</Field><Field label="Согласование">{payment.approval_state}</Field><Field label="Создана">{formatMoment(payment.created_at)}</Field></FieldGrid></CardContent></Card>;
}
