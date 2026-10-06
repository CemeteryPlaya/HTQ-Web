/**
 * «Структура проекта» на карточке «Проекта» (спек
 * docs/plans/2026-10-06-project-structure-spec.md §5).
 *
 * Оргсхема ярусами L1 → L4, как на схеме ФД: место — карточка (роль и
 * уточнение, «Офис»/«Объект», люди, «план / факт», руководитель). Схема — на
 * дату (по умолчанию сегодня) и с фильтром части. Место с планом больше трёх
 * свёрнуто («Рабочий × 10»), имена — по клику. Пустое место — «вакансия»,
 * уволенный — «уволен». Кнопки правки — только при `can_edit` от сервера
 * (руководитель своего проекта или держатель `project.structure`).
 */
import { useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { ChevronDown, ChevronRight, Plus, UserPlus } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { reportApiError } from '@/lib/apiError';

import { formatDate } from '../format';

import { AssignDialog, DateDialog, SlotDialog } from './StructureDialogs';
import {
  LEVELS, slotLabel, structureApi, structureKeys, todayIso,
  type ProjectPart, type StructureAssignment, type StructureSlot,
} from './structureApi';

type PartFilter = 'all' | ProjectPart;

/** Места с планом больше этого показываются свёрнуто. */
const COLLAPSE_ABOVE = 3;

type DateAction =
  | { kind: 'close'; slot: StructureSlot }
  | { kind: 'end'; assignment: StructureAssignment };

export function ProjectStructureSection({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const today = todayIso();
  const [on, setOn] = useState(today);
  const [part, setPart] = useState<PartFilter>('all');
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [slotDialog, setSlotDialog] = useState<{ slot: StructureSlot | null; parentId: string | null } | null>(null);
  const [assignTo, setAssignTo] = useState<StructureSlot | null>(null);
  const [dateAction, setDateAction] = useState<DateAction | null>(null);

  const structure = useQuery({
    queryKey: structureKeys.structure(projectId, on),
    queryFn: () => structureApi.structure(projectId, on),
    enabled: Boolean(on),
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: structureKeys.allOf(projectId) });

  const slots = useMemo(() => structure.data?.slots ?? [], [structure.data]);
  const byId = useMemo(() => new Map(slots.map((s) => [s.id, s])), [slots]);
  const shown = slots.filter((s) => part === 'all' || s.part === part);
  const canEdit = structure.data?.can_edit ?? false;

  const toggle = (id: string) => setExpanded((prev) => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  const partLabel = (value: ProjectPart) =>
    value === 'office' ? t('bpp.structure.office', 'Офис') : t('bpp.structure.site', 'Объект');

  const people = (slot: StructureSlot) => (
    <ul className="space-y-1">
      {slot.assignments.map((a) => (
        <li key={a.id} className="flex flex-wrap items-center gap-1.5 text-sm">
          <span className={a.dismissed ? 'text-muted-foreground line-through' : ''}>{a.full_name}</span>
          {a.dismissed && (
            <Badge variant="destructive" className="h-5 px-1.5 text-[11px]">
              {t('bpp.structure.dismissed', 'уволен')}
            </Badge>
          )}
          {a.date_to && (
            <span className="text-xs text-muted-foreground">
              {t('bpp.structure.until', 'по {{date}}', { date: formatDate(a.date_to) })}
            </span>
          )}
          {canEdit && (
            a.date_from > today ? (
              <button type="button" className="text-xs text-destructive hover:underline"
                onClick={() => {
                  structureApi.deleteAssignment(a.id).then(refresh).catch((error: unknown) =>
                    reportApiError(error, t('bpp.structure.deleteFailed', 'Не удалось удалить назначение')));
                }}>
                {t('bpp.structure.delete', 'Удалить')}
              </button>
            ) : (
              <button type="button" className="text-xs text-muted-foreground hover:text-foreground hover:underline"
                onClick={() => setDateAction({ kind: 'end', assignment: a })}>
                {t('bpp.structure.end', 'Снять')}
              </button>
            )
          )}
        </li>
      ))}
    </ul>
  );

  const card = (slot: StructureSlot) => {
    const parent = slot.parent_id ? byId.get(slot.parent_id) : null;
    const collapsed = slot.planned_headcount > COLLAPSE_ABOVE && !expanded.has(slot.id);
    return (
      <li key={slot.id} data-testid={`slot-${slot.id}`}
        className="w-full space-y-2 rounded-xl border bg-card p-3 sm:w-72">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="font-medium leading-tight">{slotLabel(slot)}</p>
            {parent && (
              <p className="text-xs text-muted-foreground">
                {t('bpp.structure.reportsTo', '↑ {{name}}', { name: slotLabel(parent) })}
              </p>
            )}
          </div>
          <Badge variant="outline" className="shrink-0">{partLabel(slot.part)}</Badge>
        </div>
        <p className="text-xs text-muted-foreground">
          {t('bpp.structure.headcount', 'план {{planned}} / факт {{actual}}',
            { planned: slot.planned_headcount, actual: slot.actual_headcount })}
        </p>
        {slot.actual_headcount === 0 ? (
          <Badge variant="secondary">{t('bpp.structure.vacancy', 'вакансия')}</Badge>
        ) : collapsed ? (
          <button type="button" onClick={() => toggle(slot.id)}
            className="inline-flex items-center gap-1 text-sm text-primary hover:underline">
            <ChevronRight className="h-3.5 w-3.5" />
            {t('bpp.structure.collapsed', '{{role}} × {{count}}', { role: slot.role.name, count: slot.actual_headcount })}
          </button>
        ) : (
          <>
            {slot.planned_headcount > COLLAPSE_ABOVE && (
              <button type="button" onClick={() => toggle(slot.id)}
                className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:underline">
                <ChevronDown className="h-3.5 w-3.5" />{t('bpp.structure.hide', 'Свернуть')}
              </button>
            )}
            {people(slot)}
          </>
        )}
        {canEdit && (
          <div className="flex flex-wrap gap-x-3 gap-y-1 border-t pt-2 text-xs">
            {slot.role.level < 4 && (
              <button type="button" className="hover:underline"
                onClick={() => setSlotDialog({ slot: null, parentId: slot.id })}>
                {t('bpp.structure.addChild', 'Добавить подчинённое место')}
              </button>
            )}
            {slot.actual_headcount < slot.planned_headcount && (
              <button type="button" className="inline-flex items-center gap-1 hover:underline"
                onClick={() => setAssignTo(slot)}>
                <UserPlus className="h-3 w-3" />{t('bpp.structure.assign', 'Назначить')}
              </button>
            )}
            <button type="button" className="hover:underline" onClick={() => setSlotDialog({ slot, parentId: null })}>
              {t('bpp.structure.edit', 'Изменить')}
            </button>
            <button type="button" className="text-destructive hover:underline"
              onClick={() => setDateAction({ kind: 'close', slot })}>
              {t('bpp.structure.close', 'Закрыть')}
            </button>
          </div>
        )}
      </li>
    );
  };

  return (
    <section className="space-y-3" data-testid="project-structure">
      <div className="flex flex-wrap items-center gap-3">
        <h3 className="text-lg font-semibold">{t('bpp.structure.heading', 'Структура проекта')}</h3>
        <div className="flex rounded-md border p-0.5 text-sm" role="group"
          aria-label={t('bpp.structure.partFilter', 'Часть проекта')}>
          {(['all', 'office', 'site'] as PartFilter[]).map((value) => (
            <button key={value} type="button" aria-pressed={part === value}
              onClick={() => setPart(value)}
              className={`rounded px-2.5 py-1 ${part === value ? 'bg-muted font-medium' : 'text-muted-foreground'}`}>
              {value === 'all' ? t('bpp.structure.all', 'Все') : partLabel(value)}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-2 text-sm">
          {t('bpp.structure.onDate', 'на дату')}
          <Input type="date" value={on} onChange={(e) => setOn(e.target.value)} className="h-8 w-40"
            aria-label={t('bpp.structure.onDate', 'на дату')} />
        </label>
        {canEdit && (
          <Button size="sm" variant="outline" className="ml-auto"
            onClick={() => setSlotDialog({ slot: null, parentId: null })}>
            <Plus className="mr-1.5 h-4 w-4" />{t('bpp.structure.addTop', 'Добавить место')}
          </Button>
        )}
      </div>

      {structure.isLoading ? (
        <Skeleton className="h-32 w-full" />
      ) : structure.isError ? (
        <p className="text-sm text-destructive">
          {t('bpp.structure.loadError', 'Не удалось загрузить структуру проекта')}
        </p>
      ) : shown.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {slots.length === 0
            ? t('bpp.structure.empty', 'Структура проекта ещё не заведена')
            : t('bpp.structure.emptyPart', 'В этой части проекта мест нет')}
        </p>
      ) : (
        <div className="space-y-4">
          {LEVELS.map((level) => {
            const row = shown.filter((s) => s.role.level === level);
            if (row.length === 0) return null;
            return (
              <div key={level} className="space-y-2" data-testid={`level-${level}`}>
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{`L${level}`}</p>
                <ul className="flex flex-wrap gap-3">{row.map(card)}</ul>
              </div>
            );
          })}
        </div>
      )}

      {canEdit && (
        <>
          <SlotDialog open={slotDialog !== null} onOpenChange={(open) => { if (!open) setSlotDialog(null); }}
            projectId={projectId} slots={slots} slot={slotDialog?.slot ?? null}
            parentId={slotDialog?.parentId ?? null} onSaved={() => { void refresh(); }} />
          <AssignDialog open={assignTo !== null} onOpenChange={(open) => { if (!open) setAssignTo(null); }}
            slot={assignTo} defaultDate={on} onSaved={() => { void refresh(); }} />
          <DateDialog open={dateAction !== null} onOpenChange={(open) => { if (!open) setDateAction(null); }}
            title={dateAction?.kind === 'close'
              ? t('bpp.structure.closeTitle', 'Закрыть место')
              : t('bpp.structure.endTitle', 'Снять сотрудника с места')}
            label={dateAction?.kind === 'close'
              ? t('bpp.structure.closeFrom', 'Место закрыто с даты')
              : t('bpp.structure.endOn', 'Последний день на месте')}
            defaultDate={on}
            onConfirm={async (value) => {
              if (dateAction?.kind === 'close') await structureApi.updateSlot(dateAction.slot.id, { closed_on: value });
              else if (dateAction?.kind === 'end') await structureApi.endAssignment(dateAction.assignment.id, value);
              await refresh();
            }} />
        </>
      )}
    </section>
  );
}
