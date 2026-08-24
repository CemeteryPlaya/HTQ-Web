import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import HRLayout from '@/components/hr/HRLayout';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { useHRLevel } from '@/hooks/useHRLevel';
import { fetchWeekTemplates, setDefaultTemplate, fetchCalendarYear, fetchShiftPatterns, deleteShiftPattern, createShiftPattern, type WeekTemplate, type CalendarDay, type ShiftPattern } from '@/api/hr';
import { useTranslation } from 'react-i18next';

const HRProductionCalendar = () => {
  const { t } = useTranslation();
  const { hasPerm } = useHRLevel();
  const qc = useQueryClient();
  const [year, setYear] = useState(new Date().getFullYear());
  const canManage = hasPerm('hr.calendar.manage');

  const { data: templates } = useQuery({ queryKey: ['week-templates'], queryFn: fetchWeekTemplates, enabled: hasPerm('hr.calendar.view') });
  const { data: days } = useQuery({ queryKey: ['calendar-year', year], queryFn: () => fetchCalendarYear(year), enabled: hasPerm('hr.calendar.view') });

  const makeDefault = useMutation({
    mutationFn: (id: number) => setDefaultTemplate(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['week-templates'] }),
  });

  const overrides = (days ?? []).filter((d: CalendarDay) => d.type === 'holiday' || d.type === 'short');

  return (
    <HRLayout title={t('hr.productionCalendar.title')} subtitle={`${year}`}>
      <section className="mb-6">
        <h3 className="font-semibold mb-2">{t('hr.productionCalendar.weekTemplates')}</h3>
        <div className="space-y-2">
          {(templates ?? []).map((tpl: WeekTemplate) => (
            <div key={tpl.id} className="flex items-center gap-2 rounded border p-2 text-sm">
              <span className="font-medium">{tpl.name}</span>
              {tpl.is_default && <Badge variant="default">{t('hr.productionCalendar.isDefault')}</Badge>}
              {canManage && !tpl.is_default && (
                <Button size="sm" variant="outline" onClick={() => makeDefault.mutate(tpl.id)}>{t('hr.productionCalendar.makeDefault')}</Button>
              )}
            </div>
          ))}
        </div>
      </section>
      <ShiftPatternsSection canManage={canManage} />
      <section>
        <div className="mb-2 flex items-center gap-3">
          <h3 className="font-semibold">{t('hr.productionCalendar.overrides', { count: overrides.length })}</h3>
          {/* Год листается вручную: праздники считаются на любой год, поэтому
              смотреть можно и прошлый, и следующий. */}
          <div className="flex items-center gap-1">
            <Button size="sm" variant="outline" onClick={() => setYear((y) => y - 1)} aria-label={t('hr.productionCalendar.prevYear')}>←</Button>
            <span className="min-w-[3.5rem] text-center font-mono text-sm">{year}</span>
            <Button size="sm" variant="outline" onClick={() => setYear((y) => y + 1)} aria-label={t('hr.productionCalendar.nextYear')}>→</Button>
          </div>
        </div>
        <div className="space-y-1 text-sm">
          {overrides.map((d) => (
            <div key={d.day} className="flex gap-3"><span className="font-mono">{d.day}</span><span>{d.type}</span><span>{d.note ?? ''}</span></div>
          ))}
          {overrides.length === 0 && <div className="text-muted-foreground">{t('hr.productionCalendar.noOverrides')}</div>}
        </div>
      </section>
    </HRLayout>
  );
};

function ShiftPatternsSection({ canManage }: { canManage: boolean }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { hasPerm } = useHRLevel();
  const { data: patterns } = useQuery({ queryKey: ['shift-patterns'], queryFn: fetchShiftPatterns, enabled: hasPerm('hr.calendar.view') });
  const [name, setName] = useState('');
  const create = useMutation({
    mutationFn: () => createShiftPattern(name || '2/2',
      [{ type: 'work', hours: 12 }, { type: 'work', hours: 12 }, { type: 'off', hours: 0 }, { type: 'off', hours: 0 }], false),
    onSuccess: () => { setName(''); qc.invalidateQueries({ queryKey: ['shift-patterns'] }); },
  });
  const del = useMutation({ mutationFn: (id: number) => deleteShiftPattern(id), onSuccess: () => qc.invalidateQueries({ queryKey: ['shift-patterns'] }) });
  return (
    <section className="mt-6">
      <h3 className="font-semibold mb-2">{t('hr.productionCalendar.shiftPatterns')}</h3>
      <div className="space-y-2">
        {(patterns ?? []).map((p: ShiftPattern) => (
          <div key={p.id} className="flex items-center gap-2 rounded border p-2 text-sm">
            <span className="font-medium">{p.name}</span>
            <span className="text-muted-foreground">
                {t('hr.productionCalendar.cycleDays', { count: p.slots.length })}
                {p.holidays_off ? t('hr.productionCalendar.holidaysOff') : ''}
              </span>
            {canManage && <Button size="sm" variant="outline" onClick={() => del.mutate(p.id)}>{t('common.delete')}</Button>}
          </div>
        ))}
      </div>
      {canManage && (
        <div className="mt-2 flex items-center gap-2">
          <input className="rounded border px-2 py-1 text-sm" placeholder={t('hr.productionCalendar.patternNamePlaceholder')} value={name} onChange={(e) => setName(e.target.value)} />
          <Button size="sm" onClick={() => create.mutate()}>{t('hr.productionCalendar.addPattern')}</Button>
        </div>
      )}
    </section>
  );
}

export default HRProductionCalendar;
