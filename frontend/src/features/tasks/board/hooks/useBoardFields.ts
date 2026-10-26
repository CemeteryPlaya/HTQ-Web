/**
 * Свои поля доски и шаблоны чек-листов в настройках доски (решение K-35,
 * этап S3). Правка поля меняет значки на карточках и поля в окне карточки,
 * поэтому перечитываются и доски, и открытые карточки.
 */
import { type QueryClient, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import { reportApiError } from '@/lib/apiError';
import type { BoardFieldType } from '@/types/tasks';

import { boardKeys, boardsApi, fieldsApi, type FieldPatch, type OptionDraft, type TemplateDraft } from '../api';
import type { BoardKey, SharedBoardKey } from '../types';

function refreshCards(queryClient: QueryClient) {
  void queryClient.invalidateQueries({ queryKey: ['tasks', 'board'] });
  void queryClient.invalidateQueries({ queryKey: ['tasks', 'card'] });
}

export function useBoardFieldDefs(key: SharedBoardKey | null, enabled = true) {
  return useQuery({
    queryKey: key ? boardKeys.fields(key) : ['tasks', 'board-fields', 'none'],
    queryFn: () => fieldsApi.list(key as SharedBoardKey),
    enabled: enabled && key !== null,
  });
}

export function useFieldActions(key: SharedBoardKey) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const done = () => {
    void queryClient.invalidateQueries({ queryKey: boardKeys.fields(key) });
    refreshCards(queryClient);
  };
  const failed = (error: unknown) =>
    reportApiError(error, t('tasks.fields.failed', 'Не удалось изменить поле доски'));
  const create = useMutation({
    mutationFn: (body: { name: string; type: BoardFieldType; options: OptionDraft[];
                         show_on_card: boolean }) => fieldsApi.create(key, body),
    onSuccess: done, onError: failed,
  });
  const update = useMutation({
    mutationFn: ({ id, ...body }: { id: number } & FieldPatch) => fieldsApi.update(id, body),
    onSuccess: done, onError: failed,
  });
  const remove = useMutation({
    mutationFn: (id: number) => fieldsApi.remove(id),
    onSuccess: done, onError: failed,
  });
  return { create, update, remove };
}

export function useBoardSettings(key: BoardKey, enabled: boolean) {
  return useQuery({
    queryKey: boardKeys.settings(key),
    queryFn: () => boardsApi.settings(key),
    enabled,
  });
}

export function useSaveTemplates(key: SharedBoardKey) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (templates: TemplateDraft[]) =>
      boardsApi.saveSettings(key, { checklist_templates: templates }),
    onSuccess: (settings) => {
      queryClient.setQueryData(boardKeys.settings(key), settings);
      void queryClient.invalidateQueries({ queryKey: ['tasks', 'card'] });
    },
    onError: (error) =>
      reportApiError(error, t('tasks.templates.failed', 'Не удалось сохранить шаблоны чек-листов')),
  });
}
