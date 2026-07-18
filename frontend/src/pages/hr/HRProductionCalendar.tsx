import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import HRLayout from '@/components/hr/HRLayout';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { useHRLevel } from '@/hooks/useHRLevel';
import { fetchWeekTemplates, setDefaultTemplate, fetchCalendarYear, fetchShiftPatterns, deleteShiftPattern, createShiftPattern, type WeekTemplate, type CalendarDay, type ShiftPattern } from '@/api/hr';

const HRProductionCalendar = () => {
  const { hasPerm } = useHRLevel();
  const qc = useQueryClient();
  const [year] = useState(new Date().getFullYear());
  const canManage = hasPerm('hr.calendar.manage');

  const { data: templates } = useQuery({ queryKey: ['week-templates'], queryFn: fetchWeekTemplates, enabled: hasPerm('hr.calendar.view') });
  const { data: days } = useQuery({ queryKey: ['calendar-year', year], queryFn: () => fetchCalendarYear(year), enabled: hasPerm('hr.calendar.view') });

  const makeDefault = useMutation({
    mutationFn: (id: number) => setDefaultTemplate(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['week-templates'] }),
  });

  const overrides = (days ?? []).filter((d: CalendarDay) => d.type === 'holiday' || d.type === 'short');

  return (
    <HRLayout title="Производственный календарь" subtitle={`${year}`}>
      <section className="mb-6">
        <h3 className="font-semibold mb-2">Шаблоны рабочей недели</h3>
        <div className="space-y-2">
          {(templates ?? []).map((t: WeekTemplate) => (
            <div key={t.id} className="flex items-center gap-2 rounded border p-2 text-sm">
              <span className="font-medium">{t.name}</span>
              {t.is_default && <Badge variant="default">по умолчанию</Badge>}
              {canManage && !t.is_default && (
                <Button size="sm" variant="outline" onClick={() => makeDefault.mutate(t.id)}>Сделать default</Button>
              )}
            </div>
          ))}
        </div>
      </section>
      <ShiftPatternsSection canManage={canManage} />
      <section>
        <h3 className="font-semibold mb-2">Исключения года ({overrides.length})</h3>
        <div className="space-y-1 text-sm">
          {overrides.map((d) => (
            <div key={d.day} className="flex gap-3"><span className="font-mono">{d.day}</span><span>{d.type}</span><span>{d.note ?? ''}</span></div>
          ))}
          {overrides.length === 0 && <div className="text-muted-foreground">Нет исключений</div>}
        </div>
      </section>
    </HRLayout>
  );
};

function ShiftPatternsSection({ canManage }: { canManage: boolean }) {
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
      <h3 className="font-semibold mb-2">Сменные графики</h3>
      <div className="space-y-2">
        {(patterns ?? []).map((p: ShiftPattern) => (
          <div key={p.id} className="flex items-center gap-2 rounded border p-2 text-sm">
            <span className="font-medium">{p.name}</span>
            <span className="text-muted-foreground">цикл {p.slots.length} дн.{p.holidays_off ? ', выходные в праздники' : ''}</span>
            {canManage && <Button size="sm" variant="outline" onClick={() => del.mutate(p.id)}>Удалить</Button>}
          </div>
        ))}
      </div>
      {canManage && (
        <div className="mt-2 flex items-center gap-2">
          <input className="rounded border px-2 py-1 text-sm" placeholder="Название (напр. 2/2)" value={name} onChange={(e) => setName(e.target.value)} />
          <Button size="sm" onClick={() => create.mutate()}>+ 2/2 шаблон</Button>
        </div>
      )}
    </section>
  );
}

export default HRProductionCalendar;
