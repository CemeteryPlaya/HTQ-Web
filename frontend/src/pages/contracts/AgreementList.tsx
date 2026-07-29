import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { FileText, Paperclip, Plus } from 'lucide-react';

import { ContractsShell } from '@/components/contracts/ContractsShell';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Skeleton } from '@/components/ui/skeleton';
import { SubmitForApproval } from '@/components/signoff/SubmitForApproval';
import { contractsApi } from '@/api/contracts';
import type { AgreementStatus } from '@/types/contracts';

/**
 * Список договоров.
 *
 * Администратор и программа показываются, хотя на договоре таких колонок
 * нет — бэкенд разворачивает их из бюджетной строки. Поэтому разойтись с
 * бюджетом они не могут.
 */

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

function formatAmount(value: string): string {
  const [whole, fraction = '00'] = value.split('.');
  return `${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ' ')},${fraction}`;
}

const AgreementList = () => {
  const { data: rows = [], isLoading, isError } = useQuery({
    queryKey: ['contracts', 'agreements'],
    queryFn: () => contractsApi.listAgreements().then((r) => r.data),
  });
  const { data: enums } = useQuery({
    queryKey: ['contracts', 'enums'],
    queryFn: () => contractsApi.getEnums().then((r) => r.data),
  });

  // Подписи статусов берём с бэкенда, а не держим свою копию — иначе при
  // добавлении статуса список молча показывал бы сырой код.
  const statusLabel = (value: AgreementStatus) =>
    enums?.agreement_status.find((option) => option.value === value)?.label ?? value;
  const paymentLabel = (value: string) =>
    enums?.payment_type.find((option) => option.value === value)?.label ?? value;

  return (
    <ContractsShell>
      <div className="mb-6 flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-3">
          <FileText className="h-7 w-7 text-muted-foreground" />
          <h1 className="text-3xl font-bold">Договоры</h1>
        </div>
        <Button asChild>
          <Link to="/contracts/agreements/new">
            <Plus className="mr-2 h-4 w-4" />
            Новый договор
          </Link>
        </Button>
      </div>

      <div className="bg-card rounded-lg border overflow-x-auto">
        {isLoading ? (
          <div className="p-6 space-y-3">
            {[0, 1, 2].map((row) => (
              <Skeleton key={row} className="h-10 w-full" />
            ))}
          </div>
        ) : isError ? (
          <p className="p-6 text-sm text-destructive">
            Не удалось загрузить договоры.
          </p>
        ) : rows.length === 0 ? (
          <div className="p-10 text-center">
            <p className="text-muted-foreground mb-4">Договоров пока нет.</p>
            <Button asChild variant="outline">
              <Link to="/contracts/agreements/new">Оформить первый</Link>
            </Button>
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Номер</TableHead>
                <TableHead>Наименование</TableHead>
                <TableHead>Контрагент</TableHead>
                <TableHead>Бюджет</TableHead>
                <TableHead className="text-right">Сумма</TableHead>
                <TableHead>Оплата</TableHead>
                <TableHead>Статус</TableHead>
                {/* Из трёх согласуемых типов только у договора согласование
                    имеет доменное последствие — оно двигает его же `status`.
                    Оси всё равно разные: согласованный по маршруту договор
                    бывает расторгнут по существу. */}
                <TableHead className="text-right">Согласование</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.id}>
                  <TableCell className="font-medium whitespace-nowrap">
                    <span className="inline-flex items-center gap-1.5">
                      {row.number}
                      {row.file_id && (
                        <Paperclip className="h-3 w-3 text-muted-foreground" />
                      )}
                    </span>
                  </TableCell>
                  <TableCell>{row.name}</TableCell>
                  <TableCell>
                    <div>{row.counterparty_name}</div>
                    <div className="text-xs text-muted-foreground tabular-nums">
                      {row.counterparty_bin_iin}
                    </div>
                  </TableCell>
                  <TableCell>
                    <div>{row.program_name}</div>
                    <div className="text-xs text-muted-foreground">
                      {row.administrator_name} · {row.period_year}
                    </div>
                  </TableCell>
                  <TableCell className="text-right tabular-nums whitespace-nowrap">
                    {formatAmount(row.amount)} {row.currency}
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {paymentLabel(row.payment_type)}
                  </TableCell>
                  <TableCell>
                    <Badge variant={STATUS_VARIANTS[row.status]}>
                      {statusLabel(row.status)}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <SubmitForApproval
                      subjectType="contracts.agreement"
                      subjectId={row.id}
                      state={row.approval_state}
                      submit={contractsApi.submitAgreement}
                      // Отправка переводит договор в on_review, а он уже
                      // занимает бюджет — остаток бюджетных строк меняется
                      // тем же действием.
                      invalidate={[['contracts', 'agreements'], ['contracts', 'budgets']]}
                    />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>
    </ContractsShell>
  );
};

export default AgreementList;
