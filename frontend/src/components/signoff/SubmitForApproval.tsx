/**
 * Кнопка «На согласование» для строки предметной аппки.
 *
 * Живёт в `components/signoff`, но ВЫЗЫВАЕТ эндпоинт предметной аппки —
 * `submit` передаётся снаружи. Общий `POST /signoff/processes` сюда не
 * годится: он принимает `subject_id` любого типа и обходит доменные права
 * мимо их владельца, поэтому на бэкенде оставлен операторским.
 *
 * Что показывается, определяет `approval_state` объекта:
 *
 * - `draft` — кнопка отправки;
 * - `rejected` — кнопка отправки повторно (отказ не терминален: объект
 *   дорабатывают и шлют снова);
 * - `pending` — ссылка на карточку идущего согласования вместо кнопки;
 * - `approved` — только плашка. Отправить согласованное заново бэкенд не
 *   запретит, но предлагать это незачем.
 *
 * **Отсутствие маршрута — не поломка.** Пока для типа не заведён активный
 * маршрут, `/submit` отвечает 409 «маршрут не настроен», и это ровно тот
 * текст, который надо показать: согласование просто ещё не включено.
 */

import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Loader2, Send } from 'lucide-react';
import type { AxiosResponse } from 'axios';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { signoffApi } from '@/api/signoff';
import type { ApprovalProcess, ApprovalState } from '@/types/signoff';

import { reportApiError } from './apiError';
import { ApprovalStateBadge } from './states';

interface Props {
  subjectType: string;
  subjectId: number;
  state: ApprovalState;
  /** Эндпоинт предметной аппки — `contractsApi.submitBudget` и соседи. */
  submit: (id: number) => Promise<AxiosResponse<ApprovalProcess>>;
  /** Ключи TanStack Query, которые надо сбросить после отправки. */
  invalidate?: unknown[][];
  size?: 'sm' | 'default';
}

export function SubmitForApproval({
  subjectType,
  subjectId,
  state,
  submit,
  invalidate = [],
  size = 'sm',
}: Props) {
  const queryClient = useQueryClient();
  const [startedId, setStartedId] = useState<number | null>(null);

  /** Идущий процесс — чтобы из строки можно было провалиться в карточку.
   *  Спрашиваем только когда объект действительно на согласовании. */
  const { data: processes = [] } = useQuery({
    queryKey: ['signoff', 'processes', { subjectType, subjectId }],
    queryFn: () =>
      signoffApi
        .listProcesses({ subject_type: subjectType, subject_id: subjectId })
        .then((r) => r.data),
    enabled: state === 'pending',
  });

  const activeProcessId =
    startedId
    ?? processes.find((process) => process.state === 'pending')?.id
    ?? processes[0]?.id
    ?? null;

  const mutation = useMutation({
    mutationFn: () => submit(subjectId).then((r) => r.data),
    onSuccess: (process) => {
      setStartedId(process.id);
      toast.success('Отправлено на согласование');
      queryClient.invalidateQueries({ queryKey: ['signoff'] });
      for (const key of invalidate) {
        queryClient.invalidateQueries({ queryKey: key });
      }
    },
    // 409 здесь — «маршрут не настроен», «уже на согласовании»,
    // «несогласованный бюджет/контрагент»; 503 — модуль выключен целиком.
    onError: (err) =>
      reportApiError(err, 'Не удалось отправить на согласование'),
  });

  if (state === 'pending') {
    return (
      <div className="flex items-center justify-end gap-2">
        <ApprovalStateBadge state={state} />
        {activeProcessId !== null && (
          <Button asChild size={size} variant="ghost">
            <Link to={`/signoff/processes/${activeProcessId}`}>Карточка</Link>
          </Button>
        )}
      </div>
    );
  }

  if (state === 'approved') {
    return (
      <div className="flex justify-end">
        <ApprovalStateBadge state={state} />
      </div>
    );
  }

  return (
    <div className="flex items-center justify-end gap-2">
      {state === 'rejected' && <ApprovalStateBadge state={state} />}
      <Button
        size={size}
        variant={state === 'rejected' ? 'outline' : 'default'}
        disabled={mutation.isPending}
        onClick={() => mutation.mutate()}
      >
        {mutation.isPending ? (
          <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
        ) : (
          <Send className="mr-1.5 h-4 w-4" />
        )}
        {state === 'rejected' ? 'Отправить снова' : 'На согласование'}
      </Button>
    </div>
  );
}
