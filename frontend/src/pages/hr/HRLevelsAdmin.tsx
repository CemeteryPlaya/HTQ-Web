import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, Save, Trash2 } from 'lucide-react';
import api from '@/api/client';
import HRLayout from '@/components/hr/HRLayout';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

interface LevelThreshold {
  id: number;
  level_number: number;
  weight_from: number;
  weight_to: number;
  label: string | null;
  color: string | null;
}

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

function toPayload(draft: LevelDraft) {
  return {
    level_number: Number(draft.level_number),
    weight_from: Number(draft.weight_from),
    weight_to: Number(draft.weight_to),
    label: draft.label || null,
    color: draft.color || DEFAULT_COLOR,
  };
}

function LevelRow({
  level,
  onSave,
  onDelete,
  saving,
}: {
  level: LevelThreshold;
  onSave: (levelNumber: number, draft: LevelDraft) => void;
  onDelete: (levelNumber: number) => void;
  saving: boolean;
}) {
  const [draft, setDraft] = useState<LevelDraft>(() => toDraft(level));

  useEffect(() => {
    setDraft(toDraft(level));
  }, [level]);

  return (
    <div className="grid gap-3 border-b px-4 py-3 last:border-b-0 lg:grid-cols-[96px_1fr_1fr_1.5fr_120px_112px] lg:items-center">
      <Input
        type="number"
        min={1}
        value={draft.level_number}
        disabled
        onChange={(e) => setDraft({ ...draft, level_number: e.target.value })}
      />
      <Input
        type="number"
        min={0}
        value={draft.weight_from}
        onChange={(e) => setDraft({ ...draft, weight_from: e.target.value })}
      />
      <Input
        type="number"
        min={0}
        value={draft.weight_to}
        onChange={(e) => setDraft({ ...draft, weight_to: e.target.value })}
      />
      <Input
        value={draft.label}
        onChange={(e) => setDraft({ ...draft, label: e.target.value })}
      />
      <div className="flex items-center gap-2">
        <input
          type="color"
          value={draft.color}
          onChange={(e) => setDraft({ ...draft, color: e.target.value })}
          className="h-9 w-12 rounded border bg-background"
        />
        <span className="font-mono text-xs text-muted-foreground">{draft.color}</span>
      </div>
      <div className="flex justify-end gap-1">
        <Button size="sm" variant="ghost" onClick={() => onSave(level.level_number, draft)} disabled={saving} title="Сохранить">
          <Save className="h-4 w-4" />
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className="text-destructive hover:text-destructive"
          onClick={() => onDelete(level.level_number)}
          disabled={saving}
          title="Удалить"
        >
          <Trash2 className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}

const HRLevelsAdmin = () => {
  const queryClient = useQueryClient();
  const [createDraft, setCreateDraft] = useState<LevelDraft>(() => toDraft());

  const { data: levels = [], isLoading } = useQuery<LevelThreshold[]>({
    queryKey: ['hr-level-thresholds'],
    queryFn: async () => (await api.get<LevelThreshold[]>('hr/v1/positions/levels/')).data,
  });

  const createMutation = useMutation({
    mutationFn: (draft: LevelDraft) => api.post('hr/v1/positions/levels/', toPayload(draft)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hr-level-thresholds'] });
      queryClient.invalidateQueries({ queryKey: ['hr-positions-v1'] });
      setCreateDraft(toDraft());
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
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hr-level-thresholds'] });
      queryClient.invalidateQueries({ queryKey: ['hr-positions-v1'] });
      queryClient.invalidateQueries({ queryKey: ['org-tree'] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (levelNumber: number) => api.delete(`hr/v1/positions/levels/${levelNumber}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hr-level-thresholds'] });
      queryClient.invalidateQueries({ queryKey: ['hr-positions-v1'] });
    },
  });

  const sortedLevels = [...levels].sort((a, b) => a.level_number - b.level_number);

  return (
    <HRLayout title="Уровни должностей" subtitle="Диапазоны весов и цвета оргструктуры">
      <div className="space-y-4">
        <section className="rounded-lg border bg-card">
          <div className="hidden border-b px-4 py-2 text-xs font-medium uppercase text-muted-foreground lg:grid lg:grid-cols-[96px_1fr_1fr_1.5fr_120px_112px]">
            <span>Уровень</span>
            <span>От</span>
            <span>До</span>
            <span>Название</span>
            <span>Цвет</span>
            <span className="text-right">Действия</span>
          </div>
          {isLoading ? (
            <div className="p-8 text-center text-sm text-muted-foreground">Загрузка...</div>
          ) : sortedLevels.length === 0 ? (
            <div className="p-8 text-center text-sm text-muted-foreground">Нет уровней</div>
          ) : (
            sortedLevels.map((level) => (
              <LevelRow
                key={level.id}
                level={level}
                saving={updateMutation.isPending || deleteMutation.isPending}
                onSave={(levelNumber, draft) => updateMutation.mutate({ levelNumber, draft })}
                onDelete={(levelNumber) => {
                  if (confirm('Удалить уровень?')) deleteMutation.mutate(levelNumber);
                }}
              />
            ))
          )}
        </section>

        <section className="rounded-lg border bg-card p-4">
          <div className="grid gap-3 lg:grid-cols-[96px_1fr_1fr_1.5fr_120px_112px] lg:items-center">
            <Input
              type="number"
              min={1}
              placeholder="L"
              value={createDraft.level_number}
              onChange={(e) => setCreateDraft({ ...createDraft, level_number: e.target.value })}
            />
            <Input
              type="number"
              min={0}
              placeholder="От"
              value={createDraft.weight_from}
              onChange={(e) => setCreateDraft({ ...createDraft, weight_from: e.target.value })}
            />
            <Input
              type="number"
              min={0}
              placeholder="До"
              value={createDraft.weight_to}
              onChange={(e) => setCreateDraft({ ...createDraft, weight_to: e.target.value })}
            />
            <Input
              placeholder="Название"
              value={createDraft.label}
              onChange={(e) => setCreateDraft({ ...createDraft, label: e.target.value })}
            />
            <input
              type="color"
              value={createDraft.color}
              onChange={(e) => setCreateDraft({ ...createDraft, color: e.target.value })}
              className="h-9 w-16 rounded border bg-background"
            />
            <Button
              onClick={() => createMutation.mutate(createDraft)}
              disabled={
                !createDraft.level_number
                || !createDraft.weight_from
                || !createDraft.weight_to
                || createMutation.isPending
              }
            >
              <Plus className="mr-2 h-4 w-4" />
              Добавить
            </Button>
          </div>
        </section>
      </div>
    </HRLayout>
  );
};

export default HRLevelsAdmin;
