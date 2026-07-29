/**
 * «Ждёт меня» — персональная очередь согласований.
 *
 * Бэкенд отдаёт СВОЮ очередь спрашивающего и ничью больше: чужую нельзя
 * запросить ни по какому параметру. Поэтому здесь нет фильтра «по
 * пользователю» — для надзора есть /signoff/processes.
 *
 * В списке только запросы на АКТИВНЫХ этапах. Запрос на этапе, до которого
 * очередь не дошла, в БД существует, но показывать его как «ждёт вас»
 * нельзя — до него может и не дойти.
 *
 * Решать может НАЗВАННЫЙ в маршруте человек — не тот, у кого админский
 * флаг. Поэтому кнопки решения есть у каждой строки этого списка и только
 * этого: попытка решить чужую задачу вернёт 409, а не 403, и админский
 * токен от этого не спасает.
 */

import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, Inbox as InboxIcon, X } from 'lucide-react';

import { SignoffShell } from '@/components/signoff/SignoffShell';
import { SubjectLink } from '@/components/signoff/SubjectLink';
import {
  DecisionDialog,
  type DecisionKind,
} from '@/components/signoff/DecisionDialog';
import { formatMoment } from '@/components/signoff/format';
import { QUORUM_LABELS } from '@/components/signoff/labels';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { signoffApi } from '@/api/signoff';
import type { InboxItem } from '@/types/signoff';

const SignoffInbox = () => {
  const queryClient = useQueryClient();
  const [target, setTarget] = useState<
    { taskId: number; kind: DecisionKind; subjectLabel: string } | null
  >(null);

  const {
    data: items = [],
    isLoading,
    isError,
  } = useQuery({
    queryKey: ['signoff', 'inbox'],
    queryFn: () => signoffApi.inbox().then((r) => r.data),
  });

  const openDecision = (item: InboxItem, kind: DecisionKind) =>
    setTarget({
      taskId: item.task_id,
      kind,
      subjectLabel:
        item.subject_title ?? `${item.subject_type} #${item.subject_id}`,
    });

  return (
    <SignoffShell>
      <div className="mb-6 flex items-center gap-3">
        <InboxIcon className="h-7 w-7 text-muted-foreground" />
        <div>
          <h1 className="text-3xl font-bold">Ждёт меня</h1>
          <p className="text-sm text-muted-foreground">
            Запросы, по которым решение за вами прямо сейчас.
          </p>
        </div>
        {items.length > 0 && (
          <Badge className="ml-auto text-base px-3 py-1">{items.length}</Badge>
        )}
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
            Не удалось загрузить очередь согласований.
          </p>
        ) : items.length === 0 ? (
          <div className="p-10 text-center">
            <p className="text-muted-foreground">
              Ничего не ждёт вашего решения.
            </p>
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Объект</TableHead>
                <TableHead>Этап</TableHead>
                <TableHead>Отправлено</TableHead>
                <TableHead className="text-right">Решение</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item) => (
                <TableRow key={item.task_id}>
                  <TableCell>
                    <SubjectLink
                      title={item.subject_title}
                      url={item.subject_url}
                      subjectType={item.subject_type}
                      subjectId={item.subject_id}
                    />
                    <div className="text-xs text-muted-foreground">
                      <Link
                        to={`/signoff/processes/${item.process_id}`}
                        className="hover:underline underline-offset-2"
                      >
                        согласование #{item.process_id}
                      </Link>
                    </div>
                  </TableCell>
                  <TableCell>
                    <div>{item.stage_name}</div>
                    <div className="text-xs text-muted-foreground">
                      {QUORUM_LABELS[item.quorum] ?? item.quorum}
                    </div>
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground whitespace-nowrap">
                    {formatMoment(item.created_at)}
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-end gap-2">
                      <Button size="sm" onClick={() => openDecision(item, 'approve')}>
                        <Check className="mr-1.5 h-4 w-4" />
                        Согласовать
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => openDecision(item, 'reject')}
                      >
                        <X className="mr-1.5 h-4 w-4" />
                        Отклонить
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>

      <DecisionDialog
        target={target}
        onOpenChange={(open) => !open && setTarget(null)}
        onDecided={() => {
          // Решение могло закрыть этап, открыть следующий и завершить весь
          // процесс — а вместе с ним сдвинуть approval_state предметного
          // объекта. Дешевле сбросить оба домена целиком, чем гадать, что
          // именно изменилось.
          queryClient.invalidateQueries({ queryKey: ['signoff'] });
          queryClient.invalidateQueries({ queryKey: ['contracts'] });
        }}
      />
    </SignoffShell>
  );
};

export default SignoffInbox;
