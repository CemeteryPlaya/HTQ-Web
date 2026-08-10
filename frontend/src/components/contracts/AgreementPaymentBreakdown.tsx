import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';

import { contractsApi } from '@/api/contracts';
import { formatMoney } from '@/components/contracts/format';
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';

interface Props {
  agreementId: number;
}

const paymentStatusLabel: Record<string, string> = {
  draft: 'Черновик',
  on_review: 'На согласовании',
  awaiting_accounting: 'Ожидает бухгалтерию',
  closed: 'Проведена',
};

interface PaymentRowProps {
  to: string;
  title: string;
  amount: string;
  currency: string;
  status: string;
}

function PaymentRow({ to, title, amount, currency, status }: PaymentRowProps) {
  return (
    <Link
      to={to}
      className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 rounded-md px-3 py-2 transition-colors hover:bg-muted"
    >
      <span className="font-medium">{title}</span>
      <span className="ml-auto tabular-nums">{formatMoney(amount, currency)}</span>
      <Badge variant={status === 'closed' ? 'default' : 'secondary'}>
        {paymentStatusLabel[status] ?? status}
      </Badge>
    </Link>
  );
}

/** Every payment document belonging to an agreement, grouped by its kind. */
export function AgreementPaymentBreakdown({ agreementId }: Props) {
  const enabled = Number.isFinite(agreementId);
  const {
    data: advancePayments = [],
    isLoading: advancePaymentsLoading,
    isError: advancePaymentsError,
  } = useQuery({
    queryKey: ['contracts', 'advance-payments', { agreementId }],
    queryFn: () =>
      contractsApi.listAdvancePayments({ agreement_id: agreementId }).then((response) => response.data),
    enabled,
  });
  const {
    data: contractPayments = [],
    isLoading: contractPaymentsLoading,
    isError: contractPaymentsError,
  } = useQuery({
    queryKey: ['contracts', 'contract-payments', { agreementId }],
    queryFn: () =>
      contractsApi.listContractPayments({ agreement_id: agreementId }).then((response) => response.data),
    enabled,
  });

  const isLoading = advancePaymentsLoading || contractPaymentsLoading;
  const isError = advancePaymentsError || contractPaymentsError;
  const count = advancePayments.length + contractPayments.length;

  return (
    <Accordion type="single" collapsible className="mt-5 border-t">
      <AccordionItem value="payments" className="border-b-0">
        <AccordionTrigger className="py-3 text-sm hover:no-underline">
          <span>
            Детализация оплат
            {!isLoading && ` · ${count}`}
          </span>
        </AccordionTrigger>
        <AccordionContent className="pb-1">
          {isLoading ? (
            <div className="space-y-2 px-3 py-1">
              <Skeleton className="h-9 w-full" />
              <Skeleton className="h-9 w-full" />
            </div>
          ) : isError ? (
            <p className="px-3 py-1 text-sm text-muted-foreground">
              Не удалось загрузить детализацию оплат.
            </p>
          ) : count === 0 ? (
            <p className="px-3 py-1 text-sm text-muted-foreground">
              По договору пока нет оплат.
            </p>
          ) : (
            <div className="space-y-3">
              {advancePayments.length > 0 && (
                <section>
                  <p className="px-3 pb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Предоплата
                  </p>
                  <div className="space-y-1">
                    {advancePayments.map((payment) => (
                      <PaymentRow
                        key={payment.id}
                        to={`/contracts/advance-payments/${payment.id}`}
                        title="Предоплата"
                        amount={payment.amount}
                        currency={payment.currency}
                        status={payment.status}
                      />
                    ))}
                  </div>
                </section>
              )}
              {contractPayments.length > 0 && (
                <section>
                  <p className="px-3 pb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Оплаты по договору
                  </p>
                  <div className="space-y-1">
                    {contractPayments.map((payment) => (
                      <PaymentRow
                        key={payment.id}
                        to={`/contracts/contract-payments/${payment.id}`}
                        title={`Оплата #${payment.id}`}
                        amount={payment.amount}
                        currency={payment.currency}
                        status={payment.status}
                      />
                    ))}
                  </div>
                </section>
              )}
            </div>
          )}
        </AccordionContent>
      </AccordionItem>
    </Accordion>
  );
}
