/**
 * EventForm — unified create/edit form for calendar events.
 *
 * Used by CalendarWidget for both "Новое событие" and "Редактировать
 * событие" dialogs. Handles:
 *   - Multi-day events (start_date + end_date).
 *   - All-day toggle that hides the time pickers and switches the
 *     submitted timestamps to local 00:00 / 23:59:59.
 *   - Event-type select (личное / отдел / общее / конференция). Department
 *     scope shows a department picker; conference reserves a room id.
 *   - Color picker (5 swatches).
 *   - Participants multi-select (ParticipantsPicker is rendered by the
 *     parent — we just expose participant_user_ids in onSubmit).
 *
 * The form itself doesn't talk to the API — it returns a clean
 * ``CalendarEvent`` patch via ``onSubmit`` and the parent component
 * pipes that through `createCalendarEvent` / `updateCalendarEvent`.
 */
import React, { useMemo, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { cn } from '@/lib/utils';
import type { CalendarEvent, CalendarEventType } from '@/types/calendar';
import type { Department } from '@/types/hr';

import { ParticipantsPicker } from './ParticipantsPicker';
import type { CalendarUserOption } from '@/api/calendar';
import { useTranslation } from 'react-i18next';

interface Props {
  /** When present, the form starts in edit mode and seeds its state from this event. */
  initial?: CalendarEvent | null;
  /** When creating, pre-fills the date inputs (e.g. clicking a day cell). */
  defaultDate?: Date | null;
  userOptions: CalendarUserOption[];
  departments: Department[];
  submitting: boolean;
  submitLabel: string;
  onCancel: () => void;
  onSubmit: (
    data: Partial<CalendarEvent> & { participant_user_ids: number[] },
  ) => void;
  /** ``initial.creator_id`` — kept separate so the picker can hide them. */
  excludeFromPicker?: number | null;
}

const COLOR_SWATCHES: { value: string; labelKey: string; bg: string }[] = [
  { value: '', labelKey: 'calendar.form.colors.default', bg: 'bg-muted' },
  { value: '#3b82f6', labelKey: 'calendar.form.colors.blue', bg: 'bg-blue-500' },
  { value: '#10b981', labelKey: 'calendar.form.colors.green', bg: 'bg-emerald-500' },
  { value: '#f59e0b', labelKey: 'calendar.form.colors.amber', bg: 'bg-amber-500' },
  { value: '#ec4899', labelKey: 'calendar.form.colors.pink', bg: 'bg-pink-500' },
  { value: '#8b5cf6', labelKey: 'calendar.form.colors.violet', bg: 'bg-violet-500' },
];

/** Two-digit pad for date / time fragments. */
const pad = (n: number) => String(n).padStart(2, '0');

/** Convert an ISO timestamp into the ``YYYY-MM-DD`` part of the local tz.
 *  The HTML ``<input type=date>`` expects the user's local calendar date,
 *  so we cannot just slice the ISO string (which is UTC).
 */
function localDatePart(iso?: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function localTimePart(iso?: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** Build an ISO from ``YYYY-MM-DD`` + ``HH:mm`` in the user's local tz. */
function combineToIso(dateStr: string, timeStr: string): string {
  if (!dateStr) return '';
  const [hh, mm] = (timeStr || '00:00').split(':').map((s) => Number(s) || 0);
  const [y, m, d] = dateStr.split('-').map((s) => Number(s));
  const dt = new Date(y, (m || 1) - 1, d || 1, hh, mm, 0, 0);
  return dt.toISOString();
}

/** End-of-day in the user's local tz: 23:59:59. */
function combineEndOfDayToIso(dateStr: string): string {
  if (!dateStr) return '';
  const [y, m, d] = dateStr.split('-').map((s) => Number(s));
  const dt = new Date(y, (m || 1) - 1, d || 1, 23, 59, 59, 999);
  return dt.toISOString();
}

export const EventForm: React.FC<Props> = ({
  initial,
  defaultDate,
  userOptions,
  departments,
  submitting,
  submitLabel,
  onCancel,
  onSubmit,
  excludeFromPicker,
}) => {
  const { t } = useTranslation();
  const todayStr = useMemo(() => {
    const ref = defaultDate ?? new Date();
    return `${ref.getFullYear()}-${pad(ref.getMonth() + 1)}-${pad(ref.getDate())}`;
  }, [defaultDate]);

  const [title, setTitle] = useState<string>(initial?.title ?? '');
  const [description, setDescription] = useState<string>(initial?.description ?? '');
  const [startDate, setStartDate] = useState<string>(
    initial ? localDatePart(initial.start_at) : todayStr,
  );
  const [endDate, setEndDate] = useState<string>(
    initial ? localDatePart(initial.end_at) || localDatePart(initial.start_at) : todayStr,
  );
  const [isAllDay, setIsAllDay] = useState<boolean>(
    initial ? Boolean(initial.is_all_day) : true,
  );
  const [startTime, setStartTime] = useState<string>(
    initial && !initial.is_all_day ? localTimePart(initial.start_at) : '09:00',
  );
  const [endTime, setEndTime] = useState<string>(
    initial && !initial.is_all_day ? localTimePart(initial.end_at) : '10:00',
  );
  const [eventType, setEventType] = useState<CalendarEventType>(
    initial?.event_type ?? 'personal',
  );
  const [departmentId, setDepartmentId] = useState<string>(
    initial?.department_id != null ? String(initial.department_id) : 'none',
  );
  const [color, setColor] = useState<string>(initial?.color ?? '');
  const [participants, setParticipants] = useState<number[]>(() => {
    if (!initial?.participants) return [];
    return initial.participants
      .map((p) => p.user_id)
      .filter((id) => id !== excludeFromPicker);
  });
  const [formError, setFormError] = useState<string | null>(null);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);
    if (!title.trim()) {
      setFormError(t('calendar.form.errors.titleRequired'));
      return;
    }
    if (!startDate) {
      setFormError(t('calendar.form.errors.startRequired'));
      return;
    }
    const effectiveEndDate = endDate || startDate;
    if (effectiveEndDate < startDate) {
      setFormError(t('calendar.form.errors.endBeforeStart'));
      return;
    }

    let startIso: string;
    let endIso: string;
    if (isAllDay) {
      startIso = combineToIso(startDate, '00:00');
      endIso = combineEndOfDayToIso(effectiveEndDate);
    } else {
      if (!startTime || !endTime) {
        setFormError(t('calendar.form.errors.timeRequired'));
        return;
      }
      if (startDate === effectiveEndDate && endTime <= startTime) {
        setFormError(t('calendar.form.errors.endTimeBeforeStart'));
        return;
      }
      startIso = combineToIso(startDate, startTime);
      endIso = combineToIso(effectiveEndDate, endTime);
    }

    const data: Partial<CalendarEvent> & { participant_user_ids: number[] } = {
      title: title.trim(),
      description: description.trim(),
      event_type: eventType,
      start_at: startIso,
      end_at: endIso,
      is_all_day: isAllDay,
      color: color || undefined,
      department_id:
        eventType === 'department' && departmentId !== 'none'
          ? Number(departmentId)
          : null,
      participant_user_ids: participants,
    };
    onSubmit(data);
  };

  return (
    <form className="p-6 md:p-8 space-y-5 bg-card" onSubmit={handleSubmit}>
      <div className="space-y-2">
        <Label htmlFor="ev-title" className="text-sm font-semibold ml-1">
          {t('calendar.form.title')}
        </Label>
        <Input
          id="ev-title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder={t('calendar.form.titlePlaceholder')}
          className="rounded-2xl h-12 bg-muted/30 border-none focus-visible:ring-primary/40"
          autoFocus
        />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label htmlFor="ev-start-date" className="text-sm font-semibold ml-1">
            {t('calendar.form.startDate')}
          </Label>
          <Input
            id="ev-start-date"
            type="date"
            value={startDate}
            onChange={(e) => {
              setStartDate(e.target.value);
              if (!endDate || endDate < e.target.value) setEndDate(e.target.value);
            }}
            className="rounded-2xl h-12 bg-muted/30 border-none focus-visible:ring-primary/40"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="ev-end-date" className="text-sm font-semibold ml-1">
            {t('calendar.form.endDate')}
          </Label>
          <Input
            id="ev-end-date"
            type="date"
            value={endDate}
            min={startDate}
            onChange={(e) => setEndDate(e.target.value)}
            className="rounded-2xl h-12 bg-muted/30 border-none focus-visible:ring-primary/40"
          />
        </div>
      </div>

      <label className="flex items-center gap-2 select-none">
        <Checkbox
          checked={isAllDay}
          onCheckedChange={(v) => setIsAllDay(Boolean(v))}
        />
        <span className="text-sm font-medium">{t('calendar.form.allDay')}</span>
      </label>

      {!isAllDay && (
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <Label htmlFor="ev-start-time" className="text-sm font-semibold ml-1">
              {t('calendar.form.startTime')}
            </Label>
            <Input
              id="ev-start-time"
              type="time"
              value={startTime}
              onChange={(e) => setStartTime(e.target.value)}
              className="rounded-2xl h-12 bg-muted/30 border-none focus-visible:ring-primary/40"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="ev-end-time" className="text-sm font-semibold ml-1">
              {t('calendar.form.endTime')}
            </Label>
            <Input
              id="ev-end-time"
              type="time"
              value={endTime}
              onChange={(e) => setEndTime(e.target.value)}
              className="rounded-2xl h-12 bg-muted/30 border-none focus-visible:ring-primary/40"
            />
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="space-y-2">
          <Label className="text-sm font-semibold ml-1">{t('calendar.form.type')}</Label>
          <Select
            value={eventType}
            onValueChange={(v) => setEventType(v as CalendarEventType)}
          >
            <SelectTrigger className="rounded-2xl h-12 bg-muted/30 border-none focus-visible:ring-primary/40">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="rounded-2xl border-none shadow-xl">
              <SelectItem value="personal" className="rounded-xl">{t('calendar.form.typePersonal')}</SelectItem>
              <SelectItem value="department" className="rounded-xl">{t('calendar.form.typeDepartment')}</SelectItem>
              <SelectItem value="common" className="rounded-xl">{t('calendar.form.typeCommon')}</SelectItem>
              <SelectItem value="conference" className="rounded-xl">{t('calendar.form.typeConference')}</SelectItem>
            </SelectContent>
          </Select>
        </div>
        {eventType === 'department' && (
          <div className="space-y-2">
            <Label className="text-sm font-semibold ml-1">{t('calendar.form.department')}</Label>
            <Select
              value={departmentId}
              onValueChange={(v) => setDepartmentId(v)}
            >
              <SelectTrigger className="rounded-2xl h-12 bg-muted/30 border-none focus-visible:ring-primary/40">
                <SelectValue placeholder={t('calendar.form.departmentPlaceholder')} />
              </SelectTrigger>
              <SelectContent className="rounded-2xl border-none shadow-xl">
                <SelectItem value="none" className="rounded-xl">{t('calendar.form.departmentNone')}</SelectItem>
                {departments.map((d) => (
                  <SelectItem key={d.id} value={String(d.id)} className="rounded-xl">
                    {d.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}
      </div>

      <div className="space-y-2">
        <Label className="text-sm font-semibold ml-1">{t('calendar.form.color')}</Label>
        <div className="flex gap-2 flex-wrap">
          {COLOR_SWATCHES.map((s) => (
            <button
              type="button"
              key={s.value || 'default'}
              onClick={() => setColor(s.value)}
              title={t(s.labelKey)}
              className={cn(
                'h-8 w-8 rounded-full border-2 transition-transform',
                s.bg,
                color === s.value
                  ? 'border-foreground scale-110'
                  : 'border-transparent hover:scale-105',
              )}
              aria-label={t(s.labelKey)}
              aria-pressed={color === s.value}
            />
          ))}
        </div>
      </div>

      <div className="space-y-2">
        <Label htmlFor="ev-description" className="text-sm font-semibold ml-1">
          {t('calendar.form.description')}
        </Label>
        <Textarea
          id="ev-description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder={t('calendar.form.descriptionPlaceholder')}
          className="min-h-[100px] rounded-2xl bg-muted/30 border-none focus-visible:ring-primary/40 p-4"
        />
      </div>

      <div className="space-y-2">
        <Label className="text-sm font-semibold ml-1">{t('calendar.form.participants')}</Label>
        <ParticipantsPicker
          options={userOptions}
          value={participants}
          onChange={setParticipants}
          placeholder={t('calendar.form.participantsPlaceholder')}
        />
        <p className="text-[11px] text-muted-foreground ml-1">
          {t('calendar.form.participantsHint')}
        </p>
      </div>

      {formError && (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {formError}
        </div>
      )}

      <div className="flex justify-end gap-3 pt-2">
        <Button type="button" variant="ghost" onClick={onCancel} className="rounded-xl px-6">
          {t('common.cancel')}
        </Button>
        <Button
          type="submit"
          disabled={submitting}
          className="px-10 rounded-xl h-11 font-bold shadow-lg shadow-primary/20"
        >
          {submitting ? t('common.saving') : submitLabel}
        </Button>
      </div>
    </form>
  );
};
