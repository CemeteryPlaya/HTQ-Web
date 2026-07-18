/** /requests — landing with Inbox / Sent tabs. */

import { CheckCircle2, Copy, Inbox, PlusCircle, Send } from 'lucide-react';
import { Link } from 'react-router-dom';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

import { RequestsLayout } from '@/features/requests/RequestsLayout';
import { useCc, useDone, useInbox, useRequestsStream, useSent } from '@/features/requests/hooks';
import type { RequestInstance } from '@/features/requests/types';

const STATUS_VARIANT: Record<RequestInstance['status'], string> = {
  draft:     'bg-slate-200 text-slate-700 hover:bg-slate-200',
  pending:   'bg-amber-100 text-amber-800 hover:bg-amber-100',
  approved:  'bg-emerald-100 text-emerald-800 hover:bg-emerald-100',
  rejected:  'bg-rose-100 text-rose-800 hover:bg-rose-100',
  cancelled: 'bg-slate-200 text-slate-700 hover:bg-slate-200',
  returned:  'bg-blue-100 text-blue-800 hover:bg-blue-100',
};

function RequestRow({ r }: { r: RequestInstance }) {
  return (
    <Link
      to={`/requests/${r.id}`}
      className="flex items-center justify-between border-b px-4 py-3 last:border-b-0 transition-colors hover:bg-muted/40"
    >
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="font-medium">{r.title || r.code}</span>
          <span className="text-xs text-muted-foreground">{r.code}</span>
        </div>
        <div className="text-xs text-muted-foreground">
          инициатор #{r.initiator_id}
          {r.total_amount != null && (
            <> · {r.total_amount} {r.currency || ''}</>
          )}
        </div>
      </div>
      <Badge variant="outline" className={STATUS_VARIANT[r.status]}>
        {r.status}
      </Badge>
    </Link>
  );
}

function ListBlock({
  data,
  emptyMessage,
}: {
  data: ReturnType<typeof useInbox>;
  emptyMessage: string;
}) {
  if (data.isLoading) {
    return (
      <div className="space-y-2 p-4">
        <Skeleton className="h-12" />
        <Skeleton className="h-12" />
        <Skeleton className="h-12" />
      </div>
    );
  }
  if (data.error) {
    return (
      <div className="px-4 py-6 text-sm text-destructive">
        Не удалось загрузить запросы.
      </div>
    );
  }
  if (!data.data?.length) {
    return (
      <div className="px-4 py-10 text-center text-sm text-muted-foreground">
        {emptyMessage}
      </div>
    );
  }
  return <div>{data.data.map((r) => <RequestRow key={r.id} r={r} />)}</div>;
}

export default function RequestsPage() {
  useRequestsStream();
  const inbox = useInbox();
  const done = useDone();
  const cc = useCc();
  const sent = useSent();

  return (
    <RequestsLayout
      title="Запросы"
      subtitle="Подача и согласование заявок"
    >
      <Tabs defaultValue="inbox" className="space-y-4">
        <TabsList>
          <TabsTrigger value="inbox" className="gap-2">
            <Inbox className="h-4 w-4" />
            Входящие
            {inbox.data && inbox.data.length > 0 && (
              <Badge variant="secondary" className="ml-1">{inbox.data.length}</Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="done" className="gap-2">
            <CheckCircle2 className="h-4 w-4" />
            Готово
            {done.data && done.data.length > 0 && (
              <Badge variant="secondary" className="ml-1">{done.data.length}</Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="cc" className="gap-2">
            <Copy className="h-4 w-4" />
            Копии
            {cc.data && cc.data.length > 0 && (
              <Badge variant="secondary" className="ml-1">{cc.data.length}</Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="sent" className="gap-2">
            <Send className="h-4 w-4" />
            Отправленные
            {sent.data && sent.data.length > 0 && (
              <Badge variant="secondary" className="ml-1">{sent.data.length}</Badge>
            )}
          </TabsTrigger>
        </TabsList>
        <div className="flex">
          <Button asChild>
            <Link to="/requests/new">
              <PlusCircle className="mr-2 h-4 w-4" />
              Создать запрос
            </Link>
          </Button>
        </div>
        <TabsContent value="inbox">
          <Card>
            <CardContent className="p-0">
              <ListBlock data={inbox} emptyMessage="Нет запросов на согласование." />
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="done">
          <Card>
            <CardContent className="p-0">
              <ListBlock data={done} emptyMessage="Вы пока не согласовывали запросов." />
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="cc">
          <Card>
            <CardContent className="p-0">
              <ListBlock data={cc} emptyMessage="Вас пока не добавляли в копию." />
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="sent">
          <Card>
            <CardContent className="p-0">
              <ListBlock data={sent} emptyMessage="Вы пока не отправляли запросов." />
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </RequestsLayout>
  );
}
