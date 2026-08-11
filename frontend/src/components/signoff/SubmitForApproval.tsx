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
 * - `rework` — кнопка отправки повторно: объект вернули с замечаниями, его
 *   правят и шлют снова;
 * - `pending` — ссылка на карточку идущего согласования вместо кнопки;
 * - `approved` и `rejected` — плашка, а с `showProcessLink` ещё и ссылка на
 *   карточку. Кнопки отправки здесь нет намеренно, и это не косметика: по
 *   решённому объекту бэкенд отвечает 409 (`engine._assert_submittable`),
 *   потому что отправлять нечего — он заперт для правки и уйдёт на новый
 *   круг ровно тем же, каким его уже видели. Открывает его «Вернуть на
 *   доработку» в карточке согласования, туда ссылка и ведёт.
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
  /**
   * Вести ли на карточку согласования у РЕШЁННОГО объекта
   * (`approved`/`rejected`) — там единственная кнопка «Вернуть на
   * доработку».
   *
   * Прополем, а не всегда, потому что ссылка стоит запроса за процессом, а
   * компонент рисуется и в строке списка: на странице из полусотни
   * согласованных бюджетов это полсотни запросов ради ссылки, по которой
   * никто не пойдёт. Карточка объекта — другое дело, там он один.
   * (У `pending` ссылка есть всегда: там за неё платит только тот, у кого
   * согласование действительно идёт.)
   */
  showProcessLink?: boolean;
  /** Показывать ли плашку состояния рядом с действием. В таблицах, где
   * состояние уже вынесено в отдельную колонку, её дублировать не нужно. */
  showState?: boolean;
}

export function SubmitForApproval({
  subjectType,
  subjectId,
  state,
  submit,
  invalidate = [],
  size = 'sm',
  showProcessLink = false,
  showState = true,
}: Props) {
  const queryClient = useQueryClient();
  const [startedId, setStartedId] = useState<number | null>(null);

  const decided = state === 'approved' || state === 'rejected';

  /** Процесс объекта — чтобы из карточки можно было провалиться в
   *  согласование: пока оно идёт (посмотреть, на ком оно) и когда решение
   *  принято (там кнопка «Вернуть на доработку», единственный способ снова
   *  начать правку). У черновика и у возвращённого на доработку процесс
   *  тоже бывает, но идти в него незачем — им нужна кнопка отправки. */
  const { data: processes = [] } = useQuery({
    queryKey: ['signoff', 'processes', { subjectType, subjectId }],
    queryFn: () =>
      signoffApi
        .listProcesses({ subject_type: subjectType, subject_id: subjectId })
        .then((r) => r.data),
    enabled: state === 'pending' || (decided && showProcessLink),
  });

  const activeProcessId =
    startedId
    ?? processes.find((process) => process.state === 'pending')?.id
    // Кругов у объекта бывает несколько (вернули — доработали — отправили
    // снова), и вести надо в ПОСЛЕДНИЙ: именно его решение сейчас держит
    // объект. Порядок в ответе не гарантирован, поэтому по максимальному id,
    // а не по первому элементу.
    ?? processes.reduce<number | null>(
      (latest, process) => (latest === null || process.id > latest ? process.id : latest),
      null,
    );

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

  // Решение принято или ещё принимается — отправлять нечего. Ссылка на
  // карточку появляется, только если её есть за что показать (см.
  // `showProcessLink`); без неё остаётся одна плашка.
  if (state === 'pending' || decided) {
    // Tables that already render approval state in a separate column pass
    // `showState={false}`. Do not leave their action cell visually empty
    // while a process link is unavailable (or intentionally suppressed).
    if (!showState && activeProcessId === null) {
      return (
        <span className="text-sm text-muted-foreground">
          {state === 'pending' ? 'Согласуется' : '—'}
        </span>
      );
    }

    return (
      <div className="flex items-center justify-end gap-2">
        {showState && <ApprovalStateBadge state={state} />}
        {/* Решать — там же: на карточке процесса есть и кнопки решения, и
            этот самый документ внутри. Здесь их нет намеренно. */}
        {activeProcessId !== null && (
          <Button asChild size={size} variant="ghost">
            <Link to={`/signoff/processes/${activeProcessId}`}>
              Карточка согласования
            </Link>
          </Button>
        )}
      </div>
    );
  }

  return (
    <div className="flex items-center justify-end gap-2">
      {state === 'rework' && showState && <ApprovalStateBadge state={state} />}
      <Button
        size={size}
        variant={state === 'rework' ? 'outline' : 'default'}
        disabled={mutation.isPending}
        onClick={() => mutation.mutate()}
      >
        {mutation.isPending ? (
          <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
        ) : (
          <Send className="mr-1.5 h-4 w-4" />
        )}
        {state === 'rework' ? 'Отправить снова' : 'На согласование'}
      </Button>
    </div>
  );
}
