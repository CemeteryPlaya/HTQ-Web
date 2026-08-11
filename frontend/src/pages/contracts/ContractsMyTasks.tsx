import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { CheckSquare, CircleDollarSign, FilePenLine, ReceiptText } from 'lucide-react';

import { contractsApi } from '@/api/contracts';
import { ContractsShell } from '@/components/contracts/ContractsShell';
import { formatMoment, formatMoney } from '@/components/contracts/format';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import type { ContractsWorkItem } from '@/types/contracts';

const actionMeta: Record<ContractsWorkItem['action'], { label: string; icon: typeof FilePenLine }> = {
  submit: { label: 'Черновики', icon: FilePenLine },
  rework: { label: 'На доработку', icon: FilePenLine },
  record_payment: { label: 'Оплата бухгалтерией', icon: CircleDollarSign },
  mark_paid: { label: 'Оплата бухгалтерией', icon: CircleDollarSign },
  submit_advance_report: { label: 'Авансовые отчёты', icon: ReceiptText },
};

function TaskCard({ item }: { item: ContractsWorkItem }) {
  const meta = actionMeta[item.action];
  const Icon = meta.icon;

  return (
    <Card>
      <CardContent className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <Badge variant={item.action === 'rework' ? 'secondary' : 'outline'}>{meta.label}</Badge>
            <span className="text-xs text-muted-foreground">{formatMoment(item.created_at)}</span>
          </div>
          <div className="flex items-start gap-3">
            <Icon className="mt-0.5 h-5 w-5 shrink-0 text-muted-foreground" />
            <div>
              <p className="font-medium">{item.title}</p>
              {item.amount && (
                <p className="mt-1 text-sm text-muted-foreground tabular-nums">
                  {formatMoney(item.amount, item.currency)}
                </p>
              )}
            </div>
          </div>
        </div>
        <Button asChild className="shrink-0">
          <Link to={item.url}>{item.action_label}</Link>
        </Button>
      </CardContent>
    </Card>
  );
}

export default function ContractsMyTasks() {
  const { data: items = [], isLoading, isError } = useQuery({
    queryKey: ['contracts', 'my-tasks'],
    queryFn: () => contractsApi.myTasks().then((response) => response.data),
  });

  return (
    <ContractsShell>
      <div className="mb-6 flex items-start gap-3">
        <CheckSquare className="mt-1 h-7 w-7 text-muted-foreground" />
        <div>
          <h1 className="text-3xl font-bold">Ждёт меня</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Действия по договорам и платежам, которые вы можете выполнить сейчас.
          </p>
        </div>
        {!isLoading && items.length > 0 && <Badge className="ml-auto px-3 py-1 text-base">{items.length}</Badge>}
      </div>

      {isLoading ? (
        <div className="space-y-3">{[0, 1, 2].map((row) => <Skeleton key={row} className="h-28 w-full" />)}</div>
      ) : isError ? (
        <Card><CardContent className="p-6 text-sm text-destructive">Не удалось загрузить ваши действия по договорам.</CardContent></Card>
      ) : items.length === 0 ? (
        <Card>
          <CardHeader className="items-center pb-2 text-center">
            <CheckSquare className="mb-2 h-8 w-8 text-muted-foreground" />
            <CardTitle>Сейчас ничего не ждёт</CardTitle>
            <CardDescription>Черновики, доработки, оформление оплат и авансовые отчёты появятся здесь, когда потребуют ваших действий.</CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <div className="space-y-3">{items.map((item, index) => <TaskCard key={`${item.action}-${item.url}-${index}`} item={item} />)}</div>
      )}
    </ContractsShell>
  );
}
