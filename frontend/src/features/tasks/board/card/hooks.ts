/**
 * Хуки окна карточки (мастер-план §7.2–7.3, этап S2). Любая правка обновляет
 * карточку в кэше и перечитывает списки задач и ленту: значки на карточке
 * доски и события в ленте должны совпадать с окном.
 */
import { useCallback } from 'react';
import {
  type InfiniteData, type QueryClient, useInfiniteQuery, useMutation, useQuery, useQueryClient,
} from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';

import {
  addTaskComment, fetchTask, unwatchTask, updateTask, updateTaskAssignees, updateTaskSupervisor,
  watchTask,
} from '@/api/tasks';
import { reportApiError } from '@/lib/apiError';
import type { AssigneeRole, Checklist, Task, TaskAccessKind, TaskStatus } from '@/types/tasks';

import { boardKeys, fieldsApi } from '../api';
import type { Board, BoardKey } from '../types';
import {
  accessApi, boardNotificationsApi, cardKeys, checklistsApi, feedApi, type PlaceBody,
  type TemplateRef,
} from './api';
import type { FeedPage } from './types';

/** Списки, где видна карточка: доски и старый реестр «Задачи» — `HRTasks` и
 * `EmployeeTasks` открывают то же окно, пока не уступят место доскам (S6). */
const TASK_LISTS = [['tasks', 'board'], ['hr-tasks'], ['employee-tasks']];

function invalidateTaskLists(queryClient: QueryClient) {
  for (const queryKey of TASK_LISTS) void queryClient.invalidateQueries({ queryKey });
}

// ── адрес ───────────────────────────────────────────────────────────────

/** Окно карточки по `?card=<id>` (K-19): открытие внутри доски пишет запись
 * в историю — «назад» закрывает окно; прямой заход закрывается без записи. */
export function useCardParam() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const location = useLocation();
  const cardId = Number(params.get('card')) || null;

  const open = useCallback((id: number) => {
    const next = new URLSearchParams(params);
    next.set('card', String(id));
    navigate({ search: next.toString() }, { state: { cardFromBoard: true } });
  }, [navigate, params]);

  const close = useCallback(() => {
    if ((location.state as { cardFromBoard?: boolean } | null)?.cardFromBoard) {
      navigate(-1);
      return;
    }
    setParams((current) => {
      const next = new URLSearchParams(current);
      next.delete('card');
      next.delete('event');
      return next;
    }, { replace: true });
  }, [location.state, navigate, setParams]);

  return { cardId, open, close };
}

/** Панель «Запросы» по `?panel=requests` — туда ведут уведомления о запросах. */
export function usePanelParam() {
  const [params, setParams] = useSearchParams();
  const open = params.get('panel') === 'requests';
  const setOpen = useCallback((value: boolean) => {
    setParams((current) => {
      const next = new URLSearchParams(current);
      if (value) next.set('panel', 'requests'); else next.delete('panel');
      return next;
    }, { replace: true });
  }, [setParams]);
  return { open, setOpen };
}

// ── карточка ────────────────────────────────────────────────────────────

export function useCard(taskId: number | null) {
  return useQuery({
    queryKey: cardKeys.card(taskId ?? 0),
    queryFn: () => fetchTask(taskId as number),
    enabled: taskId !== null,
  });
}

/** После правки: карточка — из ответа, доски и лента — перечитать. */
function useCardRefresh(taskId: number) {
  const queryClient = useQueryClient();
  return useCallback((task?: Task) => {
    if (task) queryClient.setQueryData(cardKeys.card(taskId), task);
    else void queryClient.invalidateQueries({ queryKey: cardKeys.card(taskId) });
    invalidateTaskLists(queryClient);
    void queryClient.invalidateQueries({ queryKey: cardKeys.feedPrefix(taskId) });
  }, [queryClient, taskId]);
}

export function useUpdateCard(taskId: number) {
  const { t } = useTranslation();
  const refresh = useCardRefresh(taskId);
  return useMutation({
    mutationFn: (data: Partial<Task>) => updateTask(taskId, data),
    onSuccess: (task) => refresh(task),
    onError: (error) => reportApiError(error, t('tasks.card.saveFailed', 'Не удалось сохранить задачу')),
  });
}

export function useCardPeople(taskId: number) {
  const { t } = useTranslation();
  const refresh = useCardRefresh(taskId);
  const failed = (error: unknown) =>
    reportApiError(error, t('tasks.card.peopleFailed', 'Не удалось изменить участников'));
  const assignees = useMutation({
    mutationFn: (crew: Array<{ user_id: number; role: AssigneeRole }>) =>
      updateTaskAssignees(taskId, crew),
    onSuccess: (task) => refresh(task),
    onError: failed,
  });
  const supervisor = useMutation({
    mutationFn: (userId: number | null) => updateTaskSupervisor(taskId, userId),
    onSuccess: (task) => refresh(task),
    onError: failed,
  });
  const watch = useMutation({
    mutationFn: (on: boolean) => (on ? watchTask(taskId) : unwatchTask(taskId)),
    onSuccess: (task) => refresh(task),
    onError: failed,
  });
  return { assignees, supervisor, watch };
}

/** Правки из быстрой правки на доске — по id задачи, без открытого окна. */
export function useQuickCardEdit() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const refresh = (taskId: number) => {
    void queryClient.invalidateQueries({ queryKey: cardKeys.card(taskId) });
    invalidateTaskLists(queryClient);
    void queryClient.invalidateQueries({ queryKey: cardKeys.feedPrefix(taskId) });
  };
  const failed = (error: unknown) =>
    reportApiError(error, t('tasks.card.saveFailed', 'Не удалось сохранить задачу'));
  const labels = useMutation({
    mutationFn: ({ taskId, ids }: { taskId: number; ids: number[] }) =>
      updateTask(taskId, { label_ids: ids }),
    onSuccess: (_task, { taskId }) => refresh(taskId), onError: failed,
  });
  const dates = useMutation({
    mutationFn: ({ taskId, ...body }: { taskId: number; start_date: string | null; due_date: string | null }) =>
      updateTask(taskId, body),
    onSuccess: (_task, { taskId }) => refresh(taskId), onError: failed,
  });
  const crew = useMutation({
    mutationFn: ({ taskId, assignees }: { taskId: number;
      assignees: Array<{ user_id: number; role: AssigneeRole }> }) =>
      updateTaskAssignees(taskId, assignees),
    onSuccess: (_task, { taskId }) => refresh(taskId), onError: failed,
  });
  const status = useMutation({
    mutationFn: ({ taskId, status: next }: { taskId: number; status: TaskStatus }) =>
      updateTask(taskId, { status: next }),
    onSuccess: (_task, { taskId }) => refresh(taskId),
    onError: (error) => reportApiError(error, t('tasks.board.moveFailed', 'Не удалось перенести карточку')),
  });
  return { labels, dates, crew, status };
}

// ── чек-листы ───────────────────────────────────────────────────────────

export function useChecklistActions(taskId: number) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const key = cardKeys.card(taskId);

  /** Чек-лист из ответа — на своё место в карточке; удалённый — вон. */
  const put = (checklist: Checklist | null, removedId?: number) => {
    queryClient.setQueryData<Task>(key, (task) => {
      if (!task) return task;
      const lists = (task.checklists ?? []).filter((item) => item.id !== removedId);
      if (!checklist) return { ...task, checklists: lists };
      const index = lists.findIndex((item) => item.id === checklist.id);
      const next = index === -1 ? [...lists, checklist] : lists.map((item) =>
        (item.id === checklist.id ? checklist : item));
      return { ...task, checklists: next.sort((a, b) => (a.position < b.position ? -1 : 1)) };
    });
    invalidateTaskLists(queryClient);
    void queryClient.invalidateQueries({ queryKey: cardKeys.feedPrefix(taskId) });
  };
  const failed = (error: unknown) =>
    reportApiError(error, t('tasks.checklist.failed', 'Не удалось изменить чек-лист'));

  const create = useMutation({
    mutationFn: ({ title, template }: { title: string; template?: TemplateRef }) =>
      checklistsApi.create(taskId, title, template),
    onSuccess: (checklist) => put(checklist), onError: failed,
  });
  const rename = useMutation({
    mutationFn: ({ id, title }: { id: number; title: string }) => checklistsApi.update(id, { title }),
    onSuccess: (checklist) => put(checklist), onError: failed,
  });
  const remove = useMutation({
    mutationFn: (id: number) => checklistsApi.remove(id),
    onSuccess: (_void, id) => put(null, id), onError: failed,
  });
  const addItem = useMutation({
    mutationFn: ({ checklistId, text, ...place }: { checklistId: number; text: string } & PlaceBody) =>
      checklistsApi.addItem(checklistId, { text, ...place }),
    onSuccess: (checklist) => put(checklist), onError: failed,
  });
  const updateItem = useMutation({
    mutationFn: ({ itemId, ...body }: { itemId: number; text?: string; is_done?: boolean }) =>
      checklistsApi.updateItem(itemId, body),
    // Отметка — сразу на экране; ошибка вернёт прежнее состояние.
    onMutate: async ({ itemId, is_done }) => {
      if (is_done === undefined) return undefined;
      await queryClient.cancelQueries({ queryKey: key });
      const previous = queryClient.getQueryData<Task>(key);
      queryClient.setQueryData<Task>(key, (task) => task && {
        ...task,
        checklists: (task.checklists ?? []).map((list) => {
          if (!list.items.some((item) => item.id === itemId)) return list;
          const items = list.items.map((item) => (item.id === itemId ? { ...item, is_done } : item));
          return { ...list, items, done: items.filter((item) => item.is_done).length };
        }),
      });
      return { previous };
    },
    onSuccess: (checklist) => put(checklist),
    onError: (error, _vars, context) => {
      if (context?.previous) queryClient.setQueryData(key, context.previous);
      failed(error);
    },
  });
  const removeItem = useMutation({
    mutationFn: (itemId: number) => checklistsApi.removeItem(itemId),
    onSuccess: (checklist) => put(checklist), onError: failed,
  });
  return { create, rename, remove, addItem, updateItem, removeItem };
}

// ── свои поля доски (этап S3) ────────────────────────────────────────────

/** Значение поля задачи: ответ — домашние доски карточки целиком; значки на
 * досках и лента перечитываются. */
export function useFieldValue(taskId: number) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ fieldId, value }: { fieldId: number; value: string | boolean | null }) =>
      fieldsApi.setValue(taskId, fieldId, value),
    onSuccess: ({ home_boards }) => {
      queryClient.setQueryData<Task>(cardKeys.card(taskId), (task) => task && { ...task, home_boards });
      invalidateTaskLists(queryClient);
      void queryClient.invalidateQueries({ queryKey: cardKeys.feedPrefix(taskId) });
    },
    onError: (error) => {
      // Поле на экране вернётся к значению с сервера.
      void queryClient.invalidateQueries({ queryKey: cardKeys.card(taskId) });
      reportApiError(error, t('tasks.fields.valueFailed', 'Не удалось сохранить значение поля'));
    },
  });
}

// ── лента и комментарии ─────────────────────────────────────────────────

export function useTaskFeed(taskId: number, details: boolean) {
  return useInfiniteQuery<FeedPage, Error, InfiniteData<FeedPage>, readonly unknown[], string | null>({
    queryKey: cardKeys.feed(taskId, details),
    queryFn: ({ pageParam }) => feedApi.page(taskId, details, pageParam),
    initialPageParam: null,
    getNextPageParam: (page) => page.next_before,
  });
}

export function useAddComment(taskId: number) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: string) => addTaskComment(taskId, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: cardKeys.feedPrefix(taskId) });
      invalidateTaskLists(queryClient);
    },
    onError: (error) => reportApiError(error, t('tasks.feed.commentFailed', 'Не удалось отправить комментарий')),
  });
}

// ── запросы доступа ─────────────────────────────────────────────────────

export function useAccessRequests(taskId: number, enabled = true) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const list = useQuery({
    queryKey: cardKeys.access(taskId), queryFn: () => accessApi.forTask(taskId), enabled,
  });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: cardKeys.card(taskId) });
    void queryClient.invalidateQueries({ queryKey: ['tasks', 'requests'] });
    void queryClient.invalidateQueries({ queryKey: cardKeys.feedPrefix(taskId) });
    invalidateTaskLists(queryClient);
  };
  const failed = (error: unknown) =>
    reportApiError(error, t('tasks.access.failed', 'Не удалось выполнить действие с запросом'));
  const request = useMutation({
    mutationFn: ({ kind, comment }: { kind: TaskAccessKind; comment: string }) =>
      accessApi.request(taskId, kind, comment),
    onSuccess: refresh, onError: failed,
  });
  const approve = useMutation({
    mutationFn: ({ id, mode, comment }: { id: number; mode?: 'replace' | 'delegate'; comment?: string }) =>
      accessApi.approve(id, { mode, comment }),
    onSuccess: refresh,
    // 409 «уже решено» тоже перечитывает: плашка покажет, кто решил.
    onError: (error) => { refresh(); failed(error); },
  });
  const reject = useMutation({
    mutationFn: ({ id, comment }: { id: number; comment: string }) => accessApi.reject(id, comment),
    onSuccess: refresh,
    onError: (error) => { refresh(); failed(error); },
  });
  const cancel = useMutation({
    mutationFn: (id: number) => accessApi.cancel(id), onSuccess: refresh, onError: failed,
  });
  return { list, request, approve, reject, cancel };
}

export function useRequestsInbox() {
  return useQuery({
    queryKey: cardKeys.inbox(),
    queryFn: accessApi.inbox,
    refetchOnWindowFocus: true,
    staleTime: 30_000,
  });
}

// ── уведомления доски ───────────────────────────────────────────────────

export function useBoardNotifications(key: BoardKey) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const prefix = boardKeys.boardPrefix(key);
  return useMutation({
    mutationFn: (enabled: boolean) => boardNotificationsApi.set(key, enabled),
    onMutate: async (enabled) => {
      await queryClient.cancelQueries({ queryKey: prefix });
      const previous = queryClient.getQueriesData<Board>({ queryKey: prefix });
      queryClient.setQueriesData<Board>({ queryKey: prefix }, (board) => board && {
        ...board, board: { ...board.board, notifications_enabled: enabled },
      });
      return { previous };
    },
    onError: (error, _enabled, context) => {
      for (const [queryKey, data] of context?.previous ?? []) queryClient.setQueryData(queryKey, data);
      reportApiError(error, t('tasks.board.notifications.failed', 'Не удалось изменить уведомления доски'));
    },
  });
}
