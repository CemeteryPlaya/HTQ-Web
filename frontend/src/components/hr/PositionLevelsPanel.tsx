import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, Save, Trash2 } from 'lucide-react';
import api from '@/api/client';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { errorDetail, reportApiError } from '@/lib/apiError';
import type { LevelThreshold } from '@/types/hr';
import { useTranslation } from 'react-i18next';

/**
 * Справочник уровней должностей — вкладка «Уровни» на странице /hr/positions.
 *
 * Раньше это была отдельная страница /admin/levels (HRLevelsAdmin): настройка
 * уровней и расстановка должностей по ним — одна задача, а экрана было два.
 * Ключ кэша ['hr-level-thresholds'] общий с HRPositions, поэтому канбан на
 * соседней вкладке перестраивается сам после любой правки.
 *
 * Диапазоны весов сознательно убраны из основной формы: HR оперирует уровнями,
 * а вес — внутренний порядок сортировки. При создании диапазон подбирает сервер
 * (position_service.next_free_range) по месту уровня среди существующих. Ручная
 * правка осталась — под блоком «Служебное» у каждой строки.
 */

type LevelDraft = {
  level_number: string;
  weight_from: string;
  weight_to: string;
  label: string;
  color: string;
};

const DEFAULT_COLOR = '#3b82f6';

function toDraft(level?: LevelThreshold): LevelDraft {
  return {
    level_number: level ? String(level.level_number) : '',
    weight_from: level ? String(level.weight_from) : '',
    weight_to: level ? String(level.weight_to) : '',
    label: level?.label ?? '',
    color: level?.color ?? DEFAULT_COLOR,
  };
}

function LevelRow({
  level,
  positionCount,
  onSave,
  onDelete,
  saving,
}: {
  level: LevelThreshold;
  positionCount: number;
  onSave: (levelNumber: number, draft: LevelDraft) => void;
  onDelete: (levelNumber: number, positionCount: number) => void;
  saving: boolean;
}) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState<LevelDraft>(() => toDraft(level));

  useEffect(() => {
    setDraft(toDraft(level));
  }, [level]);

  return (
    <div className="border-b px-4 py-3 last:border-b-0">
      <div className="grid gap-3 lg:grid-cols-[72px_1fr_136px_120px_112px] lg:items-center">
        <span className="text-sm font-semibold tabular-nums">L{level.level_number}</span>
        <Input
          value={draft.label}
          placeholder={t('hr.levels.namePlaceholder')}
          onChange={(e) => setDraft({ ...draft, label: e.target.value })}
        />
        <div className="flex items-center gap-2">
          <input
            type="color"
            value={draft.color}
            onChange={(e) => setDraft({ ...draft, color: e.target.value })}
            className="h-9 w-12 rounded border bg-background"
            aria-label={t('hr.levels.colorAria', { level: level.level_number })}
          />
          <span className="font-mono text-xs text-muted-foreground">{draft.color}</span>
        </div>
        <span className="text-xs text-muted-foreground">
          {t('hr.levels.positionsShort', { count: positionCount })}
        </span>
        <div className="flex justify-end gap-1">
          <Button
            size="sm"
            variant="ghost"
            onClick={() => onSave(level.level_number, draft)}
            disabled={saving}
            title={t('common.save')}
          >
            <Save className="h-4 w-4" />
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="text-destructive hover:text-destructive"
            onClick={() => onDelete(level.level_number, positionCount)}
            disabled={saving}
            title={t('common.delete')}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      </div>

      <details className="mt-2">
        <summary className="cursor-pointer text-xs text-muted-foreground">{t('hr.positions.internal')}</summary>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <span>{t('hr.levels.weightRange')}</span>
          <Input
            type="number"
            min={0}
            className="h-8 w-24"
            value={draft.weight_from}
            aria-label={t('hr.levels.weightFrom')}
            onChange={(e) => setDraft({ ...draft, weight_from: e.target.value })}
          />
          <span>—</span>
          <Input
            type="number"
            min={0}
            className="h-8 w-24"
            value={draft.weight_to}
            aria-label={t('hr.levels.weightTo')}
            onChange={(e) => setDraft({ ...draft, weight_to: e.target.value })}
          />
          <span>{t('hr.levels.savedTogether')}</span>
        </div>
      </details>
    </div>
  );
}

/** Минимум, нужный панели от списка должностей: посчитать, сколько на уровне. */
interface PositionLevelOnly {
  level: number;
}

const PositionLevelsPanel = () => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [createDraft, setCreateDraft] = useState<LevelDraft>(() => toDraft());
  const [createError, setCreateError] = useState<string | null>(null);

  const { data: levels = [], isLoading } = useQuery<LevelThreshold[]>({
    queryKey: ['hr-level-thresholds'],
    queryFn: async () => (await api.get<LevelThreshold[]>('hr/v1/positions/levels/')).data,
  });

  // Тот же ключ, что у HRPositions — на соседней вкладке список уже загружен,
  // повторного запроса не будет. Нужен, чтобы назвать последствия удаления.
  const { data: positions = [] } = useQuery<PositionLevelOnly[]>({
    queryKey: ['hr-positions-v1'],
    queryFn: async () => {
      const res = await api.get<PositionLevelOnly[]>('hr/v1/positions/?limit=200');
      return Array.isArray(res.data) ? res.data : [];
    },
  });

  const countOnLevel = (levelNumber: number) =>
    positions.filter((p) => p.level === levelNumber).length;

  const invalidateAll = () => {
    queryClient.invalidateQueries({ queryKey: ['hr-level-thresholds'] });
    queryClient.invalidateQueries({ queryKey: ['hr-positions-v1'] });
    queryClient.invalidateQueries({ queryKey: ['org-tree'] });
  };

  const createMutation = useMutation({
    // Диапазон НЕ шлём: его подберёт сервер по месту уровня в иерархии.
    mutationFn: (draft: LevelDraft) => api.post('hr/v1/positions/levels/', {
      level_number: Number(draft.level_number),
      label: draft.label || null,
      color: draft.color || DEFAULT_COLOR,
    }),
    onSuccess: () => {
      invalidateAll();
      setCreateDraft(toDraft());
      setCreateError(null);
    },
    onError: (err) => {
      // 409 «уровень уже существует» / «между L1 и L3 нет свободных весов» —
      // бэкенд объясняет причину, показываем текст прямо в строке создания.
      setCreateError(errorDetail(err) ?? t('hr.levels.addError'));
      reportApiError(err, t('hr.levels.addError'));
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ levelNumber, draft }: { levelNumber: number; draft: LevelDraft }) => (
      api.put(`hr/v1/positions/levels/${levelNumber}`, {
        weight_from: Number(draft.weight_from),
        weight_to: Number(draft.weight_to),
        label: draft.label || null,
        color: draft.color || DEFAULT_COLOR,
      })
    ),
    onSuccess: invalidateAll,
    onError: (err) => reportApiError(err, t('hr.levels.saveError')),
  });

  const deleteMutation = useMutation({
    mutationFn: (levelNumber: number) => api.delete(`hr/v1/positions/levels/${levelNumber}`),
    onSuccess: invalidateAll,
    onError: (err) => reportApiError(err, t('hr.levels.deleteError')),
  });

  const sortedLevels = [...levels].sort((a, b) => a.level_number - b.level_number);

  const confirmDelete = (levelNumber: number, positionCount: number) => {
    // Удаление порога не удаляет должности — они пересчитываются и уезжают на
    // уровень без порога. Молчаливое «Удалить уровень?» об этом не говорило.
    const message = positionCount > 0
      ? t('hr.levels.confirmDeleteWithPositions', { level: levelNumber, count: positionCount })
      : t('hr.levels.confirmDelete', { level: levelNumber });
    if (confirm(message)) deleteMutation.mutate(levelNumber);
  };

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        {t('hr.levels.panelHint')}
      </p>

      <section className="rounded-lg border bg-card">
        <div className="hidden border-b px-4 py-2 text-xs font-medium uppercase text-muted-foreground lg:grid lg:grid-cols-[72px_1fr_136px_120px_112px]">
          <span>{t('hr.levels.level')}</span>
          <span>{t('hr.pmo.name')}</span>
          <span>{t('calendar.form.color')}</span>
          <span>{t('hr.levels.positions')}</span>
          <span className="text-right">{t('common.actions')}</span>
        </div>
        {isLoading ? (
          <div className="p-8 text-center text-sm text-muted-foreground">{t('common.loading')}</div>
        ) : sortedLevels.length === 0 ? (
          <div className="p-8 text-center text-sm text-muted-foreground">{t('hr.levels.empty')}</div>
        ) : (
          sortedLevels.map((level) => (
            <LevelRow
              key={level.id}
              level={level}
              positionCount={countOnLevel(level.level_number)}
              saving={updateMutation.isPending || deleteMutation.isPending}
              onSave={(levelNumber, draft) => updateMutation.mutate({ levelNumber, draft })}
              onDelete={confirmDelete}
            />
          ))
        )}
      </section>

      <section className="rounded-lg border bg-card p-4">
        <div className="grid gap-3 lg:grid-cols-[72px_1fr_136px_112px] lg:items-center">
          <Input
            type="number"
            min={1}
            placeholder="№"
            aria-label={t('hr.levels.numberAria')}
            value={createDraft.level_number}
            onChange={(e) => setCreateDraft({ ...createDraft, level_number: e.target.value })}
          />
          <Input
            placeholder={t('hr.levels.namePlaceholder')}
            aria-label={t('hr.levels.namePlaceholder')}
            value={createDraft.label}
            onChange={(e) => setCreateDraft({ ...createDraft, label: e.target.value })}
          />
          <input
            type="color"
            aria-label={t('hr.levels.newColorAria')}
            value={createDraft.color}
            onChange={(e) => setCreateDraft({ ...createDraft, color: e.target.value })}
            className="h-9 w-16 rounded border bg-background"
          />
          <Button
            onClick={() => { setCreateError(null); createMutation.mutate(createDraft); }}
            disabled={!createDraft.level_number || createMutation.isPending}
          >
            <Plus className="mr-2 h-4 w-4" />
            {t('common.add')}
          </Button>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">
          {t('hr.levels.orderHint')}
        </p>
        {createError && (
          <div className="mt-2 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {createError}
          </div>
        )}
      </section>
    </div>
  );
};

export default PositionLevelsPanel;
