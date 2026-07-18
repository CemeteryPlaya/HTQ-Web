import React from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import HRLayout from '@/components/hr/HRLayout';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { useHRLevel } from '@/hooks/useHRLevel';
import { fetchStaffingLines, fetchStaffingSummary, deleteStaffingLine, type StaffingLine } from '@/api/hr';

const HRStaffing = () => {
  const { hasPerm } = useHRLevel();
  const qc = useQueryClient();
  const canView = hasPerm('hr.staffing.view');
  const canManage = hasPerm('hr.staffing.manage');

  const { data: lines } = useQuery({ queryKey: ['staffing-lines'], queryFn: fetchStaffingLines, enabled: canView });
  const { data: summary } = useQuery({ queryKey: ['staffing-summary'], queryFn: fetchStaffingSummary, enabled: canView });
  const del = useMutation({ mutationFn: (id: number) => deleteStaffingLine(id), onSuccess: () => { qc.invalidateQueries({ queryKey: ['staffing-lines'] }); qc.invalidateQueries({ queryKey: ['staffing-summary'] }); } });

  return (
    <HRLayout title="Штатное расписание">
      {summary && (
        <div className="mb-4 rounded-lg border p-4 text-sm">
          <div>Итого ФОТ: <span className="font-semibold">{summary.total_fot}</span></div>
          <div className="text-muted-foreground">Ставки: {summary.total_budgeted} · занято: {summary.total_filled} · вакантно: {summary.total_vacant}</div>
        </div>
      )}
      <div className="border rounded-lg overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Должность</TableHead>
              <TableHead>Отдел</TableHead>
              <TableHead>Грейд</TableHead>
              <TableHead>Ставки</TableHead>
              <TableHead>Оклад</TableHead>
              <TableHead>ФОТ</TableHead>
              {canManage && <TableHead></TableHead>}
            </TableRow>
          </TableHeader>
          <TableBody>
            {(lines ?? []).map((l: StaffingLine) => (
              <TableRow key={l.id}>
                <TableCell>#{l.position_id}</TableCell>
                <TableCell>#{l.department_id}</TableCell>
                <TableCell>{l.grade ?? '—'}</TableCell>
                <TableCell>{l.headcount}</TableCell>
                <TableCell>{l.salary}</TableCell>
                <TableCell className="font-medium">{l.fot}</TableCell>
                {canManage && <TableCell><Button size="sm" variant="outline" onClick={() => del.mutate(l.id)}>Удалить</Button></TableCell>}
              </TableRow>
            ))}
            {(lines ?? []).length === 0 && (
              <TableRow><TableCell colSpan={canManage ? 7 : 6} className="text-center py-8 text-muted-foreground">Нет строк</TableCell></TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </HRLayout>
  );
};

export default HRStaffing;
