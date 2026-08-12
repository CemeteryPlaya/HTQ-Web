import React, { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router-dom';
import { DragDropContext, Draggable, Droppable, type DropResult } from '@hello-pangea/dnd';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { GripVertical, Lock, Pencil, Plus, RefreshCw, Trash2 } from 'lucide-react';
import api from '@/api/client';
import HRLayout from '@/components/hr/HRLayout';
import PositionLevelsPanel from '@/components/hr/PositionLevelsPanel';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import { useHRLevel } from '@/hooks/useHRLevel';
import { errorDetail, reportApiError } from '@/lib/apiError';
import type { LevelThreshold, NextWeightForLevel } from '@/types/hr';

type HRLevelKey = 'junior' | 'middle' | 'senior' | 'lead';

interface PositionPermissions {
  hr_level: HRLevelKey | null;
  permissions: string[];
}

interface Position {
  id: number;
  title: string;
  department_id: number | null;
  department_name?: string;
  weight: number;
  level: number;
  grade: number;
  is_system?: boolean;
  permissions?: PositionPermissions | null;
}

interface Department {
  id: number;
  name: string;
}

interface PermissionCatalogItem {
  key: string;
  label: string;
  description: string | null;
  group: string;
}

interface PermissionCatalog {
  hr_levels: { value: HRLevelKey; label: string; description: string }[];
  permissions: PermissionCatalogItem[];
  level_presets?: Record<string, string[]>;
}

const FALLBACK_COLORS: Record<number, string> = {
  1: '#8b5cf6',
  2: '#3b82f6',
  3: '#10b981',
  4: '#f59e0b',
  5: '#6b7280',
};

function colorForLevel(level: number, thresholds?: LevelThreshold[]): string {
  return thresholds?.find((item) => item.level_number === level)?.color
    ?? FALLBACK_COLORS[level]
    ?? '#64748b';
}

function sortedPositions(items: Position[]): Position[] {
  return [...items].sort((a, b) => (
    a.level - b.level
    || a.weight - b.weight
    || a.title.localeCompare(b.title)
    || a.id - b.id
  ));
}

const HRPositions = () => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { isSenior } = useHRLevel();

  // Вкладка живёт в ?tab= — справочник уровней был отдельным адресом
  // (/admin/levels), поэтому на него должна оставаться прямая ссылка.
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = searchParams.get('tab') === 'levels' ? 'levels' : 'positions';
  const setTab = (value: string) => {
    const next = new URLSearchParams(searchParams);
    if (value === 'positions') next.delete('tab');
    else next.set('tab', value);
    setSearchParams(next, { replace: true });
  };

  const { data: positionsRaw, isLoading, error } = useQuery<Position[]>({
    queryKey: ['hr-positions-v1'],
    queryFn: async () => {
      const res = await api.get<Position[]>('hr/v1/positions/?limit=200');
      return Array.isArray(res.data) ? res.data : [];
    },
  });
  const positions = positionsRaw ?? [];

  const { data: departments } = useQuery<Department[]>({
    queryKey: ['hr-departments'],
    queryFn: async () => (await api.get<Department[]>('hr/v1/departments/')).data,
  });

  const { data: thresholds } = useQuery<LevelThreshold[]>({
    queryKey: ['hr-level-thresholds'],
    queryFn: async () => (await api.get<LevelThreshold[]>('hr/v1/positions/levels/')).data,
  });

  const { data: permissionsCatalog } = useQuery<PermissionCatalog>({
    queryKey: ['hr-permissions-catalog'],
    queryFn: async () => (await api.get<PermissionCatalog>('hr/v1/positions/permissions-catalog/')).data,
  });

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingPos, setEditingPos] = useState<Position | null>(null);
  const [form, setForm] = useState<{
    title: string;
    department_id: string;
    level: string;
    weight: string;
    grade: string;
    hr_level: HRLevelKey | '';
    permissions: string[];
  }>({ title: '', department_id: '', level: '', weight: '100', grade: '1', hr_level: '', permissions: [] });
  // Сообщение о том, что серверу не удалось подобрать свободный вес в уровне
  // (диапазон порога занят целиком) — вес тогда вводится вручную.
  const [levelWeightError, setLevelWeightError] = useState<string | null>(null);
  // Ошибка сохранения — отдельно от тоста: диалог остаётся открытым, и тост
  // в углу экрана легко пропустить, продолжая жать «Сохранить».
  const [saveError, setSaveError] = useState<string | null>(null);
  const [departmentFilter, setDepartmentFilter] = useState('all');

  const editingIsSystem = !!editingPos?.is_system;

  const visiblePositions = useMemo(
    () => sortedPositions(
      positions.filter((p) => departmentFilter === 'all' || String(p.department_id) === departmentFilter),
    ),
    [positions, departmentFilter],
  );

  const orderedLevels = useMemo(() => {
    const fromThresholds = (thresholds ?? []).map((item) => item.level_number);
    const fromPositions = visiblePositions.map((item) => item.level);
    return Array.from(new Set([...fromThresholds, ...fromPositions])).sort((a, b) => a - b);
  }, [thresholds, visiblePositions]);

  const sortedThresholds = useMemo(
    () => [...(thresholds ?? [])].sort((a, b) => a.level_number - b.level_number),
    [thresholds],
  );

  // Порог выбранного в диалоге уровня + проверка веса на попадание в диапазон.
  // Ту же проверку делает бэкенд (422), здесь — чтобы не отправлять заведомо
  // отклоняемое сохранение.
  const selectedThreshold = sortedThresholds.find(
    (item) => item.level_number === Number(form.level),
  );
  const weightOutOfLevelRange = Boolean(
    selectedThreshold
    && form.weight !== ''
    && (Number(form.weight) < selectedThreshold.weight_from
      || Number(form.weight) > selectedThreshold.weight_to),
  );

  const groups = useMemo(() => {
    const map = new Map<number, Position[]>();
    for (const level of orderedLevels) map.set(level, []);
    for (const pos of visiblePositions) {
      if (!map.has(pos.level)) map.set(pos.level, []);
      map.get(pos.level)!.push(pos);
    }
    return map;
  }, [orderedLevels, visiblePositions]);

  const saveMutation = useMutation({
    mutationFn: async () => {
      const permissions = (form.hr_level || form.permissions.length > 0)
        ? {
            hr_level: form.hr_level || null,
            permissions: form.permissions,
          }
        : null;
      // For system positions: skip title/department/is_active in the
      // payload — backend rejects those edits with 409.
      const payload: Record<string, unknown> = {
        weight: Number(form.weight),
        grade: Number(form.grade),
        permissions,
      };
      // level — не поле модели, а выбор веса: бэкенд проверит, что вес попал
      // в диапазон порога (422 иначе), и выведет level из веса как обычно.
      if (form.level) payload.level = Number(form.level);
      if (!editingIsSystem) {
        payload.title = form.title;
        payload.department_id = Number(form.department_id);
      }
      if (editingPos) {
        return api.put(`hr/v1/positions/${editingPos.id}/`, payload);
      }
      return api.post('hr/v1/positions/', payload);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hr-positions-v1'] });
      queryClient.invalidateQueries({ queryKey: ['org-tree'] });
      setDialogOpen(false);
      setEditingPos(null);
      setSaveError(null);
      setForm({ title: '', department_id: '', level: '', weight: '100', grade: '1', hr_level: '', permissions: [] });
    },
    onError: (err) => {
      // 409 (вес занят / системная должность) и 422 (вес вне диапазона) —
      // бэкенд присылает готовое объяснение, показываем его, а не «ошибка».
      setSaveError(errorDetail(err) ?? 'Не удалось сохранить должность');
      reportApiError(err, 'Не удалось сохранить должность');
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.delete(`hr/v1/positions/${id}/`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['hr-positions-v1'] }),
    onError: (err) => reportApiError(err, 'Не удалось удалить должность'),
  });

  const moveMutation = useMutation({
    mutationFn: (payload: {
      id: number;
      before_position_id?: number;
      after_position_id?: number;
      target_level: number;
      optimistic_weight: number;
    }) => api.patch(`hr/v1/positions/${payload.id}/move`, {
      before_position_id: payload.before_position_id,
      after_position_id: payload.after_position_id,
      target_level: payload.target_level,
    }),
    onMutate: async (payload) => {
      await queryClient.cancelQueries({ queryKey: ['hr-positions-v1'] });
      const previous = queryClient.getQueryData<Position[]>(['hr-positions-v1']);
      queryClient.setQueryData<Position[]>(['hr-positions-v1'], (old = []) => (
        old.map((item) => (
          item.id === payload.id
            ? { ...item, level: payload.target_level, weight: payload.optimistic_weight }
            : item
        ))
      ));
      return { previous };
    },
    onError: (err, _payload, context) => {
      if (context?.previous) {
        queryClient.setQueryData(['hr-positions-v1'], context.previous);
      }
      // Откат карточки на место без объяснения выглядел как «перетаскивание
      // не сработало»: 409 при коллизии веса внутри уровня тут реален.
      reportApiError(err, 'Не удалось переместить должность');
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['hr-positions-v1'] });
      queryClient.invalidateQueries({ queryKey: ['org-tree'] });
    },
  });

  const rebalanceMutation = useMutation({
    mutationFn: (level?: number) => api.post('hr/v1/positions/rebalance', level ? { level } : {}),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['hr-positions-v1'] }),
    onError: (err) => reportApiError(err, 'Не удалось выровнять порядок'),
  });

  /** Подставляет свободный вес выбранного уровня. Считает сервер: вес глобально
   *  уникален, а фронт видит лишь первую страницу должностей. */
  const suggestWeightForLevel = async (levelNumber: number) => {
    try {
      const res = await api.get<NextWeightForLevel>(
        `hr/v1/positions/levels/${levelNumber}/next-weight`,
      );
      setForm((prev) => (
        Number(prev.level) === levelNumber ? { ...prev, weight: String(res.data.weight) } : prev
      ));
      setLevelWeightError(null);
    } catch (err) {
      setLevelWeightError(errorDetail(err, 'Не удалось подобрать вес — задайте его вручную.'));
    }
  };

  const changeLevel = (value: string) => {
    setForm((prev) => ({ ...prev, level: value }));
    setLevelWeightError(null);
    const levelNumber = Number(value);
    if (levelNumber) void suggestWeightForLevel(levelNumber);
  };

  const startCreate = () => {
    setEditingPos(null);
    setLevelWeightError(null);
    setSaveError(null);
    const firstLevel = sortedThresholds[0];
    setForm({
      title: '',
      department_id: '',
      level: firstLevel ? String(firstLevel.level_number) : '',
      weight: String(firstLevel?.weight_from ?? 100),
      grade: '1',
      hr_level: '',
      permissions: [],
    });
    setDialogOpen(true);
    if (firstLevel) void suggestWeightForLevel(firstLevel.level_number);
  };

  const startEdit = (pos: Position) => {
    setEditingPos(pos);
    setLevelWeightError(null);
    setSaveError(null);
    setForm({
      title: pos.title,
      department_id: pos.department_id ? String(pos.department_id) : '',
      level: String(pos.level),
      weight: String(pos.weight),
      grade: String(pos.grade),
      hr_level: pos.permissions?.hr_level ?? '',
      permissions: pos.permissions?.permissions ?? [],
    });
    setDialogOpen(true);
  };

  const togglePermission = (key: string) => {
    setForm((prev) => ({
      ...prev,
      permissions: prev.permissions.includes(key)
        ? prev.permissions.filter((p) => p !== key)
        : [...prev.permissions, key],
    }));
  };

  const groupedPermissions = useMemo(() => {
    const groups = new Map<string, PermissionCatalogItem[]>();
    for (const item of permissionsCatalog?.permissions ?? []) {
      if (!groups.has(item.group)) groups.set(item.group, []);
      groups.get(item.group)!.push(item);
    }
    return Array.from(groups.entries());
  }, [permissionsCatalog]);

  const onDragEnd = (result: DropResult) => {
    if (!result.destination || !isSenior) return;
    const sourceLevel = Number(result.source.droppableId);
    const targetLevel = Number(result.destination.droppableId);
    const sourceItems = [...(groups.get(sourceLevel) ?? [])];
    const targetItems = sourceLevel === targetLevel ? sourceItems : [...(groups.get(targetLevel) ?? [])];
    const [moved] = sourceItems.splice(result.source.index, 1);
    if (!moved) return;
    const nextTarget = sourceLevel === targetLevel ? sourceItems : targetItems;
    nextTarget.splice(result.destination.index, 0, moved);

    const before = nextTarget[result.destination.index - 1];
    const after = nextTarget[result.destination.index + 1];
    const threshold = thresholds?.find((item) => item.level_number === targetLevel);
    const optimisticWeight = before && after
      ? Math.floor((before.weight + after.weight) / 2)
      : before
        ? before.weight + 100
        : after
          ? Math.max(threshold?.weight_from ?? 0, after.weight - 100)
          : threshold?.weight_from ?? 0;

    moveMutation.mutate({
      id: moved.id,
      before_position_id: before?.id,
      after_position_id: after?.id,
      target_level: targetLevel,
      optimistic_weight: optimisticWeight,
    });
  };

  // Загрузка/ошибка списка должностей — состояние ВКЛАДКИ, а не страницы:
  // ранний return из компонента отрезал бы доступ к вкладке «Уровни», хотя
  // пороги грузятся отдельным запросом и обычно уже на руках.
  const positionsView = isLoading ? (
    <div className="rounded-lg border bg-card p-8 text-center">{t('hr.common.loading')}</div>
  ) : error ? (
    <div className="rounded-lg border bg-card p-8 text-center text-red-500">
      {t('hr.pages.positions.error')}
    </div>
  ) : (
    <div className="flex flex-col gap-4">
        <div className="rounded-3xl border bg-card p-4 shadow-2xs">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex flex-wrap items-center gap-3">
              <Select value={departmentFilter} onValueChange={setDepartmentFilter}>
                <SelectTrigger className="h-9 w-48 text-xs rounded-xl bg-muted/30">
                  <SelectValue placeholder="Все отделы" />
                </SelectTrigger>
                <SelectContent className="rounded-2xl">
                  <SelectItem value="all">Все отделы</SelectItem>
                  {departments?.map((department) => (
                    <SelectItem key={department.id} value={String(department.id)}>
                      {department.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <div className="text-xs font-semibold text-muted-foreground whitespace-nowrap">
                {t('hr.common.total')}: {visiblePositions.length}
                {positions.length !== visiblePositions.length ? ` / ${positions.length}` : ''}
              </div>
            </div>

            {isSenior && (
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  className="rounded-xl h-9 text-xs"
                  onClick={() => rebalanceMutation.mutate(undefined)}
                  disabled={rebalanceMutation.isPending}
                >
                  <RefreshCw className="mr-2 h-3.5 w-3.5" />
                  Выровнять порядок
                </Button>
                <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
                  <DialogTrigger asChild>
                    <Button size="sm" onClick={startCreate} className="h-9 gap-2 rounded-xl bg-primary text-primary-foreground hover:bg-primary/90 font-semibold shadow-2xs">
                      <Plus className="h-4 w-4" />
                      {t('hr.pages.positions.create', 'Создать должность')}
                    </Button>
                  </DialogTrigger>
                  <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto">
                    <DialogHeader>
                      <DialogTitle className="flex items-center gap-2">
                        {editingPos ? t('hr.pages.positions.edit') : t('hr.pages.positions.new')}
                        {editingIsSystem && (
                          <Badge variant="secondary" className="gap-1">
                            <Lock className="h-3 w-3" /> Системная
                          </Badge>
                        )}
                      </DialogTitle>
                    </DialogHeader>
                    {editingIsSystem && (
                      <p className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
                        Системные должности — это базовая структура организации. Название и отдел изменить нельзя, но вы можете настроить вес, грейд и права.
                      </p>
                    )}
                    <div className="grid gap-4">
                      <label className="grid gap-2 text-sm">
                      {t('hr.pages.positions.fields.title')}
                      <Input
                        value={form.title}
                        onChange={(e) => setForm({ ...form, title: e.target.value })}
                        disabled={editingIsSystem}
                      />
                    </label>
                    <label className="grid gap-2 text-sm">
                      {t('hr.pages.positions.fields.department')}
                      <Select
                        value={form.department_id}
                        onValueChange={(v) => setForm({ ...form, department_id: v })}
                        disabled={editingIsSystem}
                      >
                        <SelectTrigger>
                          <SelectValue placeholder={t('hr.pages.positions.placeholders.selectDepartment')} />
                        </SelectTrigger>
                        <SelectContent>
                          {departments?.map((department) => (
                            <SelectItem key={department.id} value={String(department.id)}>
                              {department.name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </label>
                    <label className="grid gap-2 text-sm">
                      {t('hr.pages.positions.fields.level')}
                      <Select value={form.level} onValueChange={changeLevel}>
                        <SelectTrigger>
                          <SelectValue placeholder="Выберите уровень" />
                        </SelectTrigger>
                        <SelectContent>
                          {sortedThresholds.map((threshold) => (
                            <SelectItem
                              key={threshold.id}
                              value={String(threshold.level_number)}
                            >
                              <span className="flex items-center gap-2">
                                <span
                                  className="h-2.5 w-2.5 rounded-full"
                                  style={{
                                    backgroundColor: colorForLevel(threshold.level_number, thresholds),
                                  }}
                                />
                                L{threshold.level_number}{threshold.label ? `: ${threshold.label}` : ''}
                              </span>
                            </SelectItem>
                          ))}
                          {/* Уровень должности может не покрываться ни одним порогом
                              (fallback L5 на бэкенде) — показываем его, чтобы селект
                              не выглядел пустым и не терял текущее значение. */}
                          {form.level && !selectedThreshold && (
                            <SelectItem value={form.level}>
                              L{form.level} — не заведён в справочнике
                            </SelectItem>
                          )}
                        </SelectContent>
                      </Select>
                      <span className="text-xs text-muted-foreground">
                        {sortedThresholds.length === 0
                          ? 'Уровни ещё не заведены — добавьте их на вкладке «Уровни».'
                          : 'Место должности в иерархии оргструктуры.'}
                      </span>
                    </label>

                    <label className="grid gap-2 text-sm">
                      Грейд
                      <Input
                        type="number"
                        min={1}
                        max={10}
                        value={form.grade}
                        onChange={(e) => setForm({ ...form, grade: e.target.value })}
                      />
                      <span className="text-xs text-muted-foreground">
                        Квалификационный разряд 1–10. С уровнем в иерархии не связан.
                      </span>
                    </label>

                    {/* Вес — внутренний порядок сортировки, HR им не оперирует:
                        уровень задаётся селектом выше, порядок внутри уровня —
                        перетаскиванием карточек. Поле оставлено для разбора
                        нештатных ситуаций и по умолчанию свёрнуто. */}
                    <details className="rounded-lg border bg-muted/30 p-3">
                      <summary className="cursor-pointer text-sm font-medium text-muted-foreground">
                        Служебное
                      </summary>
                      <label className="mt-3 grid gap-2 text-sm">
                        Вес
                        <Input
                          type="number"
                          min={0}
                          aria-label="Вес"
                          value={form.weight}
                          onChange={(e) => setForm({ ...form, weight: e.target.value })}
                        />
                        {weightOutOfLevelRange && selectedThreshold ? (
                          <span className="text-xs text-destructive">
                            Вес вне диапазона уровня L{selectedThreshold.level_number}
                            {' '}({selectedThreshold.weight_from}–{selectedThreshold.weight_to})
                          </span>
                        ) : selectedThreshold ? (
                          <span className="text-xs text-muted-foreground">
                            Порядок внутри уровня. Диапазон L{selectedThreshold.level_number}:
                            {' '}{selectedThreshold.weight_from}–{selectedThreshold.weight_to}
                          </span>
                        ) : null}
                        {levelWeightError && (
                          <span className="text-xs text-destructive">{levelWeightError}</span>
                        )}
                      </label>
                    </details>

                    <div className="grid gap-2 rounded-lg border bg-muted/30 p-3">
                      <div className="text-sm font-semibold">Уровень доступа HR</div>
                      <p className="text-xs text-muted-foreground">
                        Определяет, что сотрудник на этой должности видит и может делать в модуле HR.
                      </p>
                      <Select
                        value={form.hr_level || 'none'}
                        onValueChange={(v) => {
                          const level = v === 'none' ? '' : (v as HRLevelKey);
                          const preset = level
                            ? (permissionsCatalog?.level_presets?.[level] ?? [])
                            : [];
                          setForm({ ...form, hr_level: level, permissions: preset });
                        }}
                      >
                        <SelectTrigger>
                          <SelectValue placeholder="Без HR-доступа" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="none">Без HR-доступа</SelectItem>
                          {permissionsCatalog?.hr_levels.map((lvl) => (
                            <SelectItem key={lvl.value} value={lvl.value}>
                              {lvl.label} — {lvl.description}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>

                    <div className="grid gap-2 rounded-lg border bg-muted/30 p-3">
                      <div className="text-sm font-semibold">Дополнительные права</div>
                      <p className="text-xs text-muted-foreground">
                        Отметьте конкретные действия, доступные носителю должности. Применяются поверх уровня доступа.
                      </p>
                      <div className="grid gap-3">
                        {groupedPermissions.map(([group, items]) => (
                          <div key={group} className="grid gap-1">
                            <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                              {group}
                            </div>
                            <div className="grid grid-cols-1 gap-1 sm:grid-cols-2">
                              {items.map((item) => (
                                <label
                                  key={item.key}
                                  className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1 text-sm hover:bg-muted"
                                >
                                  <input
                                    type="checkbox"
                                    checked={form.permissions.includes(item.key)}
                                    onChange={() => togglePermission(item.key)}
                                    className="h-4 w-4"
                                  />
                                  <span className="truncate">{item.label}</span>
                                </label>
                              ))}
                            </div>
                          </div>
                        ))}
                        {groupedPermissions.length === 0 && (
                          <div className="text-xs text-muted-foreground">Каталог прав недоступен.</div>
                        )}
                      </div>
                    </div>

                    {saveError && (
                      <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                        {saveError}
                      </div>
                    )}

                    <div className="flex justify-end gap-2">
                      <Button variant="outline" onClick={() => setDialogOpen(false)}>
                        {t('hr.common.cancel')}
                      </Button>
                      <Button
                        onClick={() => { setSaveError(null); saveMutation.mutate(); }}
                        disabled={
                          (!editingIsSystem && (!form.title || !form.department_id))
                          || weightOutOfLevelRange
                          || saveMutation.isPending
                        }
                      >
                        {saveMutation.isPending ? t('hr.common.saving') : t('hr.common.save')}
                      </Button>
                    </div>
                  </div>
                </DialogContent>
              </Dialog>
            </div>
          )}
        </div>
        </div>

        <div className="flex flex-wrap gap-2">
          {(thresholds ?? []).map((threshold) => {
            const color = colorForLevel(threshold.level_number, thresholds);
            return (
              <span
                key={threshold.id}
                className="inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium"
                style={{ borderColor: color, backgroundColor: `${color}1a`, color }}
              >
                L{threshold.level_number}{threshold.label ? `: ${threshold.label}` : ''}
                <span className="tabular-nums opacity-70">
                  {(groups.get(threshold.level_number) ?? []).length}
                </span>
              </span>
            );
          })}
        </div>

        <DragDropContext onDragEnd={onDragEnd}>
          <div className="grid gap-4 xl:grid-cols-2">
            {orderedLevels.map((level) => {
              const color = colorForLevel(level, thresholds);
              const threshold = thresholds?.find((item) => item.level_number === level);
              const items = groups.get(level) ?? [];
              return (
                // `min-w-0`: у grid-элемента min-width по умолчанию auto, и
                // карточки должностей внутри распирали колонку шире экрана.
                <section key={level} className="min-w-0 rounded-lg border bg-card">
                  <div className="flex items-center justify-between gap-3 border-b px-4 py-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span
                          className="h-3 w-3 rounded-full"
                          style={{ backgroundColor: color }}
                        />
                        <h2 className="truncate text-sm font-semibold">
                          L{level}{threshold?.label ? `: ${threshold.label}` : ''}
                        </h2>
                        <Badge variant="outline">{items.length}</Badge>
                      </div>
                      {!threshold && (
                        <p className="mt-1 text-xs text-muted-foreground">
                          Уровень не заведён в справочнике
                        </p>
                      )}
                    </div>
                    {isSenior && (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => rebalanceMutation.mutate(level)}
                        disabled={rebalanceMutation.isPending}
                        title="Выровнять порядок внутри уровня"
                      >
                        <RefreshCw className="h-4 w-4" />
                      </Button>
                    )}
                  </div>

                  <Droppable droppableId={String(level)} isDropDisabled={!isSenior}>
                    {(provided, snapshot) => (
                      <div
                        ref={provided.innerRef}
                        {...provided.droppableProps}
                        className={`min-h-[96px] space-y-2 p-3 ${snapshot.isDraggingOver ? 'bg-muted/60' : ''}`}
                      >
                        {items.map((position, index) => (
                          <Draggable
                            key={position.id}
                            draggableId={String(position.id)}
                            index={index}
                            isDragDisabled={!isSenior}
                          >
                            {(dragProvided, dragSnapshot) => (
                              <div
                                ref={dragProvided.innerRef}
                                {...dragProvided.draggableProps}
                                className={`flex items-center gap-3 rounded-lg border bg-background px-3 py-2 shadow-sm ${dragSnapshot.isDragging ? 'shadow-lg' : ''}`}
                              >
                                <button
                                  type="button"
                                  className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-muted"
                                  title="Перетащить"
                                  {...dragProvided.dragHandleProps}
                                >
                                  <GripVertical className="h-4 w-4" />
                                </button>
                                <div className="min-w-0 flex-1">
                                  <div className="flex items-center gap-2">
                                    <span className="truncate text-sm font-medium">{position.title}</span>
                                    {position.is_system && (
                                      <Badge variant="secondary" className="gap-1 text-[10px]" title="Системная должность — нельзя удалить или переименовать">
                                        <Lock className="h-3 w-3" /> Системная
                                      </Badge>
                                    )}
                                    {position.permissions?.hr_level && (
                                      <Badge variant="outline" className="text-[10px] uppercase">
                                        {position.permissions.hr_level}
                                      </Badge>
                                    )}
                                  </div>
                                  <div className="truncate text-xs text-muted-foreground">
                                    {position.department_name ?? 'Без отдела'} · грейд {position.grade}
                                  </div>
                                </div>
                                {isSenior && (
                                  <div className="flex items-center gap-1">
                                    <Button size="sm" variant="ghost" onClick={() => startEdit(position)} title={t('hr.common.edit')}>
                                      <Pencil className="h-4 w-4" />
                                    </Button>
                                    <Button
                                      size="sm"
                                      variant="ghost"
                                      className="text-destructive hover:text-destructive disabled:text-muted-foreground"
                                      disabled={!!position.is_system}
                                      onClick={() => {
                                        if (position.is_system) return;
                                        if (confirm(t('hr.pages.positions.deleteConfirm'))) {
                                          deleteMutation.mutate(position.id);
                                        }
                                      }}
                                      title={position.is_system ? 'Системную должность нельзя удалить' : t('hr.common.delete')}
                                    >
                                      <Trash2 className="h-4 w-4" />
                                    </Button>
                                  </div>
                                )}
                              </div>
                            )}
                          </Draggable>
                        ))}
                        {provided.placeholder}
                        {items.length === 0 && (
                          <div className="flex min-h-[64px] items-center justify-center rounded-lg border border-dashed text-sm text-muted-foreground">
                            Нет должностей
                          </div>
                        )}
                      </div>
                    )}
                  </Droppable>
                </section>
              );
            })}
          </div>
        </DragDropContext>
    </div>
  );

  return (
    <HRLayout title={t('hr.pages.positions.title')} subtitle={t('hr.pages.positions.subtitle')}>
      {isSenior ? (
        <Tabs value={tab} onValueChange={setTab}>
          <TabsList>
            <TabsTrigger value="positions">{t('hr.pages.positions.tabs.positions')}</TabsTrigger>
            <TabsTrigger value="levels">{t('hr.pages.positions.tabs.levels')}</TabsTrigger>
          </TabsList>
          <TabsContent value="positions" className="mt-4">{positionsView}</TabsContent>
          <TabsContent value="levels" className="mt-4">
            <PositionLevelsPanel />
          </TabsContent>
        </Tabs>
      ) : positionsView}
    </HRLayout>
  );
};

export default HRPositions;
