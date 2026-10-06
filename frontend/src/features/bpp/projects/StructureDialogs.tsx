/**
 * Диалоги правки проектной структуры: место (завести / изменить),
 * назначение сотрудника и дата (закрыть место, снять сотрудника).
 *
 * Правила дерева, плана и дат проверяет сервер (409 `E-PRJ-05`, 422
 * `E-PRJ-06`) — диалог показывает его текст (`reportApiError`) и остаётся
 * открытым. Список руководителей — только места строго выше по уровню, как
 * требует сервер, чтобы заведомо отвергаемый выбор не предлагался.
 */
import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { reportApiError } from '@/lib/apiError';

import {
  slotLabel, structureApi, structureKeys, type ProjectPart, type StructureSlot,
} from './structureApi';

const selectClass = 'h-9 w-full rounded-md border bg-background px-2 text-sm';

interface SlotDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
  slots: StructureSlot[];
  /** Изменить это место; без него — завести новое. */
  slot?: StructureSlot | null;
  /** Руководитель нового места по умолчанию («Добавить подчинённое место»). */
  parentId?: string | null;
  onSaved: () => void;
}

export function SlotDialog({
  open, onOpenChange, projectId, slots, slot, parentId, onSaved,
}: SlotDialogProps) {
  const { t } = useTranslation();
  const roles = useQuery({
    queryKey: structureKeys.roles(true),
    queryFn: () => structureApi.roles(true),
    enabled: open && !slot,
  });
  const [roleId, setRoleId] = useState<number | null>(null);
  const [parent, setParent] = useState<string>('');
  const [part, setPart] = useState<ProjectPart>('office');
  const [title, setTitle] = useState('');
  const [planned, setPlanned] = useState('1');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setRoleId(slot ? slot.role.id : null);
    setParent(slot ? slot.parent_id ?? '' : parentId ?? '');
    setPart(slot ? slot.part : 'office');
    setTitle(slot?.title ?? '');
    setPlanned(String(slot?.planned_headcount ?? 1));
  }, [open, slot, parentId]);

  const level = slot ? slot.role.level : roles.data?.find((r) => r.id === roleId)?.level ?? null;
  const parentOptions = slots.filter((s) => s.id !== slot?.id && level !== null && s.role.level < level);

  const chooseRole = (value: string) => {
    const id = Number(value) || null;
    setRoleId(id);
    const role = roles.data?.find((r) => r.id === id);
    if (role) setPart(role.default_part);
  };

  const save = async () => {
    if (busy || (!slot && roleId === null)) return;
    setBusy(true);
    const common = {
      parent_id: parent || null, part, title: title.trim(),
      planned_headcount: Math.max(1, Number(planned) || 1),
    };
    try {
      if (slot) await structureApi.updateSlot(slot.id, common);
      else await structureApi.createSlot(projectId, { role_id: roleId as number, ...common });
      onSaved();
      onOpenChange(false);
    } catch (error) {
      reportApiError(error, t('bpp.structure.saveFailed', 'Не удалось сохранить место'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {slot ? t('bpp.structure.editSlot', 'Изменить место') : t('bpp.structure.newSlot', 'Новое место')}
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          {!slot && (
            <div className="space-y-1">
              <Label htmlFor="slot-role">{t('bpp.structure.role', 'Роль')}</Label>
              <select id="slot-role" className={selectClass} value={roleId ?? ''}
                onChange={(e) => chooseRole(e.target.value)}>
                <option value="">{t('bpp.structure.chooseRole', '— выберите роль —')}</option>
                {(roles.data ?? []).map((r) => (
                  <option key={r.id} value={r.id}>{`L${r.level} · ${r.name}`}</option>
                ))}
              </select>
            </div>
          )}
          <div className="space-y-1">
            <Label htmlFor="slot-parent">{t('bpp.structure.parent', 'Подчиняется')}</Label>
            <select id="slot-parent" className={selectClass} value={parent}
              onChange={(e) => setParent(e.target.value)}>
              <option value="">{t('bpp.structure.noParent', '— никому (только L1) —')}</option>
              {parentOptions.map((s) => (
                <option key={s.id} value={s.id}>{`L${s.role.level} · ${slotLabel(s)}`}</option>
              ))}
            </select>
          </div>
          <div className="space-y-1">
            <Label htmlFor="slot-part">{t('bpp.structure.part', 'Часть')}</Label>
            <select id="slot-part" className={selectClass} value={part}
              onChange={(e) => setPart(e.target.value as ProjectPart)}>
              <option value="office">{t('bpp.structure.office', 'Офис')}</option>
              <option value="site">{t('bpp.structure.site', 'Объект')}</option>
            </select>
          </div>
          <div className="space-y-1">
            <Label htmlFor="slot-title">{t('bpp.structure.title', 'Уточнение')}</Label>
            <Input id="slot-title" value={title} maxLength={255}
              placeholder={t('bpp.structure.titleHint', 'например, сметчик или бригада 2')}
              onChange={(e) => setTitle(e.target.value)} />
          </div>
          <div className="space-y-1">
            <Label htmlFor="slot-planned">{t('bpp.structure.planned', 'Людей по плану')}</Label>
            <Input id="slot-planned" type="number" min={1} max={999} value={planned}
              onChange={(e) => setPlanned(e.target.value)} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>{t('common.cancel', 'Отмена')}</Button>
          <Button onClick={() => { void save(); }} disabled={busy || (!slot && roleId === null)}>
            {t('common.save', 'Сохранить')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

interface AssignDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  slot: StructureSlot | null;
  defaultDate: string;
  onSaved: () => void;
}

export function AssignDialog({ open, onOpenChange, slot, defaultDate, onSaved }: AssignDialogProps) {
  const { t } = useTranslation();
  const [query, setQuery] = useState('');
  const [employeeId, setEmployeeId] = useState<number | null>(null);
  const [dateFrom, setDateFrom] = useState(defaultDate);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setQuery('');
    setEmployeeId(null);
    setDateFrom(defaultDate);
  }, [open, defaultDate]);

  const q = query.trim();
  const found = useQuery({
    queryKey: structureKeys.employees(q),
    queryFn: () => structureApi.employees(q),
    enabled: open && q.length >= 2,
  });

  const save = async () => {
    if (busy || !slot || employeeId === null || !dateFrom) return;
    setBusy(true);
    try {
      await structureApi.assign(slot.id, { employee_id: employeeId, date_from: dateFrom });
      onSaved();
      onOpenChange(false);
    } catch (error) {
      reportApiError(error, t('bpp.structure.assignFailed', 'Не удалось назначить сотрудника'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {t('bpp.structure.assignTo', 'Назначить на место «{{slot}}»', { slot: slot ? slotLabel(slot) : '' })}
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1">
            <Label htmlFor="assign-search">{t('bpp.structure.employee', 'Сотрудник')}</Label>
            <Input id="assign-search" value={query} autoFocus
              placeholder={t('bpp.structure.searchEmployee', 'Фамилия или имя, от 2 букв')}
              onChange={(e) => { setQuery(e.target.value); setEmployeeId(null); }} />
            {q.length >= 2 && (
              <ul className="max-h-48 overflow-y-auto rounded-md border" role="listbox">
                {(found.data ?? []).length === 0 ? (
                  <li className="px-3 py-2 text-sm text-muted-foreground">
                    {found.isLoading ? t('common.loading', 'Загрузка…') : t('bpp.structure.nobody', 'Никого не найдено')}
                  </li>
                ) : (found.data ?? []).map((e) => (
                  <li key={e.id} role="option" aria-selected={employeeId === e.id}>
                    <button type="button" onClick={() => setEmployeeId(e.id)}
                      className={`w-full px-3 py-2 text-left text-sm hover:bg-muted ${employeeId === e.id ? 'bg-muted font-medium' : ''}`}>
                      {e.full_name}
                      <span className="ml-2 text-xs text-muted-foreground">{e.position_title}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="space-y-1">
            <Label htmlFor="assign-from">{t('bpp.structure.dateFrom', 'С даты')}</Label>
            <Input id="assign-from" type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>{t('common.cancel', 'Отмена')}</Button>
          <Button onClick={() => { void save(); }} disabled={busy || employeeId === null || !dateFrom}>
            {t('bpp.structure.assign', 'Назначить')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

interface DateDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  label: string;
  defaultDate: string;
  onConfirm: (date: string) => Promise<void>;
}

/** Одна дата: закрыть место «с даты» или снять сотрудника «по дату». */
export function DateDialog({ open, onOpenChange, title, label, defaultDate, onConfirm }: DateDialogProps) {
  const { t } = useTranslation();
  const [value, setValue] = useState(defaultDate);
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (open) setValue(defaultDate); }, [open, defaultDate]);

  const confirm = async () => {
    if (busy || !value) return;
    setBusy(true);
    try {
      await onConfirm(value);
      onOpenChange(false);
    } catch (error) {
      reportApiError(error, t('bpp.structure.saveFailed', 'Не удалось сохранить место'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader><DialogTitle>{title}</DialogTitle></DialogHeader>
        <div className="space-y-1">
          <Label htmlFor="structure-date">{label}</Label>
          <Input id="structure-date" type="date" value={value} onChange={(e) => setValue(e.target.value)} />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>{t('common.cancel', 'Отмена')}</Button>
          <Button onClick={() => { void confirm(); }} disabled={busy || !value}>{t('common.confirm', 'Подтвердить')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
