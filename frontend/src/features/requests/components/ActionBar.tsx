/** Action buttons for a request instance — styled with shadcn primitives.
 *  Visible buttons depend on status + whether the current user is the
 *  initiator / an approver / elevated. */

import { useState } from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Textarea } from '@/components/ui/textarea';

import { useApprove, useCancel, useReject, useRequestChanges } from '@/features/requests/hooks';
import type { RequestInstance } from '@/features/requests/types';

interface Props {
  instance: RequestInstance;
  currentUserId: number;
  isElevated?: boolean;
  canApprove?: boolean;
}

export function ActionBar({ instance, currentUserId, isElevated = false, canApprove = false }: Props) {
  const [comment, setComment] = useState('');
  const approve = useApprove(instance.id);
  const reject = useReject(instance.id);
  const requestChanges = useRequestChanges(instance.id);
  const cancel = useCancel(instance.id);

  const isInitiator = instance.initiator_id === currentUserId;
  const isPending = instance.status === 'pending';
  const showApproverButtons = isPending && canApprove;
  const showCancel = isPending && (isInitiator || isElevated);

  if (!isPending) {
    return (
      <Card>
        <CardContent className="py-3 text-sm text-muted-foreground">
          Запрос в статусе «{instance.status}». Действия недоступны.
        </CardContent>
      </Card>
    );
  }

  const runMutation =
    (m: { mutateAsync: (v: string) => Promise<unknown> }, ok: string) =>
    async () => {
      try {
        await m.mutateAsync(comment);
        toast.success(ok);
        setComment('');
      } catch (e: any) {
        toast.error(e?.response?.data?.detail ?? e?.message ?? 'Не удалось выполнить действие');
      }
    };

  return (
    <Card>
      <CardContent className="space-y-3 py-4">
        {(showApproverButtons || showCancel) && (
          <Textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="Комментарий (необязательно)"
            rows={2}
          />
        )}
        <div className="flex flex-wrap gap-2">
          {showApproverButtons && (
            <>
              <Button
                disabled={approve.isPending}
                onClick={runMutation(approve, 'Одобрено')}
                className="bg-emerald-600 hover:bg-emerald-700"
              >
                Одобрить
              </Button>
              <Button
                disabled={reject.isPending}
                onClick={runMutation(reject, 'Отклонено')}
                variant="destructive"
              >
                Отклонить
              </Button>
              <Button
                disabled={requestChanges.isPending}
                onClick={runMutation(requestChanges, 'Возвращено на доработку')}
                variant="outline"
              >
                Вернуть на доработку
              </Button>
            </>
          )}
          {showCancel && (
            <Button
              variant="outline"
              disabled={cancel.isPending}
              onClick={async () => {
                try {
                  await cancel.mutateAsync();
                  toast.success('Запрос отменён');
                } catch (e: any) {
                  toast.error(e?.response?.data?.detail ?? e?.message ?? 'Не удалось отменить');
                }
              }}
            >
              Отменить
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
