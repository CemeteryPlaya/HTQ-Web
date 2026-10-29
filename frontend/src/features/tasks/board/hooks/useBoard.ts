/**
 * Доска, список досок, перенос, быстрое добавление и настройки колонок
 * (мастер-план §7.2). Перенос оптимистичный: карточка сразу встаёт на новое
 * место, ошибка сервера возвращает её назад и показывает его текст.
 */
import { useEffect } from 'react';
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import { reportApiError } from '@/lib/apiError';
import { fallback } from '@/lib/fallback';
import type { TaskStatus } from '@/types/tasks';

import { boardKeys, boardsApi, type CardMoveBody } from '../api';
import type { Board, BoardFilters, BoardKey, ColumnsSettings } from '../types';

export function useBoardsList() {
  return useQuery({ queryKey: boardKeys.list(), queryFn: boardsApi.list, staleTime: 60_000 });
}

export function useBoard(key: BoardKey, filters: BoardFilters) {
  return useQuery({
    queryKey: boardKeys.board(key, filters),
    queryFn: () => boardsApi.board(key, filters),
    // Смена фильтра не мигает пустой доской.
    placeholderData: keepPreviousData,
  });
}

/** Карточка на новом месте в копии доски: из старой колонки — вон, в
 * целевую — на позицию после `before_id` (или перед `after_id`). */
export function moveInBoard(board: Board, taskId: number, body: CardMoveBody): Board {
  let moved = null as Board['columns'][number]['cards'][number] | null;
  const columns = board.columns.map((column) => {
    const index = column.cards.findIndex((item) => item.id === taskId);
    if (index === -1) return column;
    moved = column.cards[index];
    return { ...column, count: column.count - 1,
      cards: column.cards.filter((item) => item.id !== taskId) };
  });
  if (!moved) return board;
  const card = { ...(moved as NonNullable<typeof moved>), status: body.status };
  return {
    ...board,
    columns: columns.map((column) => {
      if (column.status !== body.status) return column;
      const cards = [...column.cards];
      let at = cards.length;
      if (body.before_id != null) {
        const index = cards.findIndex((item) => item.id === body.before_id);
        if (index !== -1) at = index + 1;
      } else if (body.after_id != null) {
        const index = cards.findIndex((item) => item.id === body.after_id);
        if (index !== -1) at = index;
      }
      cards.splice(at, 0, card);
      return { ...column, count: column.count + 1, cards };
    }),
  };
}

export function useMoveCard(key: BoardKey, filters: BoardFilters) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const queryKey = boardKeys.board(key, filters);
  return useMutation({
    mutationFn: ({ taskId, body }: { taskId: number; body: CardMoveBody }) =>
      boardsApi.move(key, taskId, body),
    onMutate: async ({ taskId, body }) => {
      await queryClient.cancelQueries({ queryKey });
      const previous = queryClient.getQueryData<Board>(queryKey);
      if (previous) queryClient.setQueryData(queryKey, moveInBoard(previous, taskId, body));
      return { previous };
    },
    onError: (error, _vars, context) => {
      if (context?.previous) queryClient.setQueryData(queryKey, context.previous);
      reportApiError(error, t('tasks.board.moveFailed', 'Не удалось перенести карточку'));
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: boardKeys.boardPrefix(key) }),
  });
}

export function useQuickAdd(key: BoardKey) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { summary: string; status: TaskStatus; department_id?: number;
                         project_id?: number }) => boardsApi.quickAdd(key, body),
    onError: (error) => reportApiError(error, t('tasks.board.addFailed', 'Не удалось добавить карточку')),
    onSettled: () => queryClient.invalidateQueries({ queryKey: boardKeys.boardPrefix(key) }),
  });
}

export function useSaveColumns(key: BoardKey) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (columns: Partial<ColumnsSettings>) => boardsApi.saveSettings(key, { columns }),
    onError: (error) => reportApiError(error, t('tasks.board.settingsFailed', 'Не удалось сохранить настройки доски')),
    onSettled: () => queryClient.invalidateQueries({ queryKey: boardKeys.boardPrefix(key) }),
  });
}

/** «Показать ещё» в колонке: следующие карточки дописываются к уже
 * показанным. Перезапрос доски (после переноса) снова показывает первые 200. */
export function useLoadMoreColumn(key: BoardKey, filters: BoardFilters) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const queryKey = boardKeys.board(key, filters);
  return useMutation({
    mutationFn: ({ status, offset }: { status: TaskStatus; offset: number }) =>
      boardsApi.column(key, filters, status, offset),
    onSuccess: (page, { status }) => {
      const fresh = page.columns.find((column) => column.status === status);
      if (!fresh) return;
      queryClient.setQueryData<Board>(queryKey, (board) => board && {
        ...board,
        columns: board.columns.map((column) => {
          if (column.status !== status) return column;
          const known = new Set(column.cards.map((card) => card.id));
          return {
            ...column,
            count: fresh.count,
            has_more: fresh.has_more,
            cards: [...column.cards, ...fresh.cards.filter((card) => !known.has(card.id))],
          };
        }),
      });
    },
    onError: (error) => reportApiError(error, t('tasks.board.loadMoreFailed', 'Не удалось загрузить карточки')),
  });
}

/** Новое название карточки — сразу на доске, ошибка возвращает прежнее. */
export function useRenameCard(key: BoardKey) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const prefix = boardKeys.boardPrefix(key);
  return useMutation({
    mutationFn: ({ taskId, summary }: { taskId: number; summary: string }) =>
      boardsApi.rename(taskId, summary),
    onMutate: async ({ taskId, summary }) => {
      await queryClient.cancelQueries({ queryKey: prefix });
      const previous = queryClient.getQueriesData<Board>({ queryKey: prefix });
      queryClient.setQueriesData<Board>({ queryKey: prefix }, (board) => board && {
        ...board,
        columns: board.columns.map((column) => ({
          ...column,
          cards: column.cards.map((card) => (card.id === taskId ? { ...card, summary } : card)),
        })),
      });
      return { previous };
    },
    onError: (error, _vars, context) => {
      for (const [queryKey, data] of context?.previous ?? []) queryClient.setQueryData(queryKey, data);
      reportApiError(error, t('tasks.board.renameFailed', 'Не удалось переименовать задачу'));
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: prefix }),
  });
}

/** Задачу открыли — она больше не «новая» на личной доске (K-28). Отметка
 * не главное в открытии задачи: её сбой не мешает работе и не показывается. */
export function useMarkSeen(taskId: number | null) {
  const queryClient = useQueryClient();
  useEffect(() => {
    if (!taskId) return;
    boardsApi.seen(taskId)
      .then(() => queryClient.invalidateQueries({ queryKey: ['tasks', 'board', 'personal'] }))
      .catch((error: unknown) => fallback('tasks.board.seen_failed', undefined, {
        reason: 'отметка «просмотрено» не дошла до сервера',
        expected: true,
        cause: error,
        context: { taskId },
      }));
  }, [taskId, queryClient]);
}
