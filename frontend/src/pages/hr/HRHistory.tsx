import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import api from '@/api/client';
import HRLayout from '@/components/hr/HRLayout';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useHRLevel } from '@/hooks/useHRLevel';

interface HistoryRecord {
  id: number;
  employee: number;
  employee_name: string;
  event_type: string;
  event_date: string;
  from_department: number | null;
  from_department_name: string | null;
  to_department: number | null;
  to_department_name: string | null;
  from_position: number | null;
  from_position_title: string | null;
  to_position: number | null;
  to_position_title: string | null;
  order_number: string;
  comment: string;
  created_by_name: string | null;
  created_at: string;
}

interface EmployeeOption {
  id: number;
  full_name: string;
}

interface Department {
  id: number;
  name: string;
}

interface Position {
  id: number;
  title: string;
  department: number | null;
}

const EVENT_TYPES = ['hired', 'dismissed', 'transfer', 'promotion', 'demotion', 'other'] as const;

const EVENT_COLORS: Record<string, string> = {
  hired: 'bg-green-500',
  dismissed: 'bg-red-500',
  transfer: 'bg-blue-500',
  promotion: 'bg-yellow-500',
  demotion: 'bg-orange-500',
  other: 'bg-gray-500',
};

const HRHistory = () => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { isSenior } = useHRLevel();

  const { data: records, isLoading, error } = useQuery({
    queryKey: ['hr-personnel-history'],
    queryFn: async () => {
      const res = await api.get<HistoryRecord[]>('hr/v1/personnel-history/');
      return res.data;
    },
  });

  const { data: employees } = useQuery({
    queryKey: ['hr-employees'],
    queryFn: async () => {
      const res = await api.get<EmployeeOption[]>('hr/v1/employees/');
      return res.data;
    },
  });

  const { data: departments } = useQuery({
    queryKey: ['hr-departments'],
    queryFn: async () => {
      const res = await api.get<Department[]>('hr/v1/departments/');
      return res.data;
    },
  });

  const { data: positions } = useQuery({
    queryKey: ['hr-positions'],
    queryFn: async () => {
      const res = await api.get<Position[]>('hr/v1/positions/');
      return res.data;
    },
  });

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<HistoryRecord | null>(null);
  const [form, setForm] = useState({
    employee: 'none',
    event_type: 'hired',
    event_date: new Date().toISOString().slice(0, 10),
    from_department: '',
    to_department: '',
    from_position: '',
    to_position: '',
    order_number: '',
    comment: '',
  });

  const [filterType, setFilterType] = useState('all');

  const saveMutation = useMutation({
    mutationFn: async () => {
      const payload: any = {
        employee: Number(form.employee),
        event_type: form.event_type,
        event_date: form.event_date,
        from_department: form.from_department ? Number(form.from_department) : null,
        to_department: form.to_department ? Number(form.to_department) : null,
        from_position: form.from_position ? Number(form.from_position) : null,
        to_position: form.to_position ? Number(form.to_position) : null,
        order_number: form.order_number,
        comment: form.comment,
      };
      if (editing) {
        return (await api.put(`hr/v1/personnel-history/${editing.id}/`, payload)).data;
      }
      return (await api.post('hr/v1/personnel-history/', payload)).data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hr-personnel-history'] });
      closeDialog();
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.delete(`hr/v1/personnel-history/${id}/`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['hr-personnel-history'] }),
  });

  const closeDialog = () => {
    setDialogOpen(false);
    setEditing(null);
    setForm({
      employee: 'none',
      event_type: 'hired',
      event_date: new Date().toISOString().slice(0, 10),
      from_department: '',
      to_department: '',
      from_position: '',
      to_position: '',
      order_number: '',
      comment: '',
    });
  };

  const startCreate = () => {
    closeDialog();
    setDialogOpen(true);
  };

  const startEdit = (rec: HistoryRecord) => {
    setEditing(rec);
    setForm({
      employee: String(rec.employee),
      event_type: rec.event_type,
      event_date: rec.event_date,
      from_department: rec.from_department ? String(rec.from_department) : '',
      to_department: rec.to_department ? String(rec.to_department) : '',
      from_position: rec.from_position ? String(rec.from_position) : '',
      to_position: rec.to_position ? String(rec.to_position) : '',
      order_number: rec.order_number || '',
      comment: rec.comment || '',
    });
    setDialogOpen(true);
  };

  const showTransferFields = form.event_type === 'transfer' || form.event_type === 'promotion' || form.event_type === 'demotion';

  const filteredRecords = (records ?? []).filter((r) => {
    if (filterType === 'all') return true;
    return r.event_type === filterType;
  });

  if (isLoading) {
    return (
      <HRLayout title={t('hr.pages.history.title')} subtitle={t('hr.pages.history.subtitle')}>
        <div className="rounded-2xl border bg-card/70 p-8 text-center">{t('hr.common.loading')}</div>
      </HRLayout>
    );
  }
  if (error) {
    return (
      <HRLayout title={t('hr.pages.history.title')} subtitle={t('hr.pages.history.subtitle')}>
        <div className="rounded-2xl border bg-card/70 p-8 text-center text-red-500">
          {t('hr.pages.history.error')}
        </div>
      </HRLayout>
    );
  }

  return (
    <HRLayout title={t('hr.pages.history.title')} subtitle={t('hr.pages.history.subtitle')}>
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div className="text-sm text-muted-foreground">{t('hr.common.total')}: {filteredRecords.length}</div>
        <Dialog open={dialogOpen} onOpenChange={(v) => { if (!v) closeDialog(); else setDialogOpen(true); }}>
          <DialogTrigger asChild>
            <Button onClick={startCreate}>{t('hr.pages.history.create')}</Button>
          </DialogTrigger>
          <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
            <DialogHeader>
              <DialogTitle>{editing ? t('hr.pages.history.edit') : t('hr.pages.history.new')}</DialogTitle>
            </DialogHeader>
            <div className="grid gap-4">
              <label className="grid gap-2 text-sm">
                {t('hr.pages.history.fields.employee')}
                <Select value={form.employee} onValueChange={(v) => setForm({ ...form, employee: v })}>
                  <SelectTrigger>
                    <SelectValue placeholder={t('hr.pages.history.placeholders.selectEmployee')} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">{t('hr.pages.history.placeholders.selectEmployee')}</SelectItem>
                    {employees?.map((e) => (
                      <SelectItem key={e.id} value={String(e.id)}>{e.full_name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </label>

              <div className="grid gap-4 md:grid-cols-2">
                <label className="grid gap-2 text-sm">
                  {t('hr.pages.history.fields.eventType')}
                  <Select value={form.event_type} onValueChange={(v) => setForm({ ...form, event_type: v })}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {EVENT_TYPES.map((et) => (
                        <SelectItem key={et} value={et}>{t(`hr.pages.history.eventTypes.${et}`)}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </label>
                <label className="grid gap-2 text-sm">
                  {t('hr.pages.history.fields.eventDate')}
                  <Input type="date" value={form.event_date} onChange={(e) => setForm({ ...form, event_date: e.target.value })} />
                </label>
              </div>

              {showTransferFields && (
                <>
                  <div className="grid gap-4 md:grid-cols-2">
                    <label className="grid gap-2 text-sm">
                      {t('hr.pages.history.fields.fromDepartment')}
                      <Select value={form.from_department || 'none'} onValueChange={(v) => setForm({ ...form, from_department: v === 'none' ? '' : v })}>
                        <SelectTrigger><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="none">—</SelectItem>
                          {departments?.map((d) => (
                            <SelectItem key={d.id} value={String(d.id)}>{d.name}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </label>
                    <label className="grid gap-2 text-sm">
                      {t('hr.pages.history.fields.toDepartment')}
                      <Select value={form.to_department || 'none'} onValueChange={(v) => setForm({ ...form, to_department: v === 'none' ? '' : v })}>
                        <SelectTrigger><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="none">—</SelectItem>
                          {departments?.map((d) => (
                            <SelectItem key={d.id} value={String(d.id)}>{d.name}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </label>
                  </div>
                  <div className="grid gap-4 md:grid-cols-2">
                    <label className="grid gap-2 text-sm">
                      {t('hr.pages.history.fields.fromPosition')}
                      <Select value={form.from_position || 'none'} onValueChange={(v) => setForm({ ...form, from_position: v === 'none' ? '' : v })}>
                        <SelectTrigger><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="none">—</SelectItem>
                          {positions?.map((p) => (
                            <SelectItem key={p.id} value={String(p.id)}>{p.title}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </label>
                    <label className="grid gap-2 text-sm">
                      {t('hr.pages.history.fields.toPosition')}
                      <Select value={form.to_position || 'none'} onValueChange={(v) => setForm({ ...form, to_position: v === 'none' ? '' : v })}>
                        <SelectTrigger><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="none">—</SelectItem>
                          {positions?.map((p) => (
                            <SelectItem key={p.id} value={String(p.id)}>{p.title}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </label>
                  </div>
                </>
              )}

              <label className="grid gap-2 text-sm">
                {t('hr.pages.history.fields.orderNumber')}
                <Input value={form.order_number} onChange={(e) => setForm({ ...form, order_number: e.target.value })} />
              </label>

              <label className="grid gap-2 text-sm">
                {t('hr.pages.history.fields.comment')}
                <Textarea value={form.comment} onChange={(e) => setForm({ ...form, comment: e.target.value })} />
              </label>

              <div className="flex justify-end gap-2">
                <Button variant="outline" onClick={closeDialog}>{t('hr.common.cancel')}</Button>
                <Button
                  onClick={() => saveMutation.mutate()}
                  disabled={form.employee === 'none' || !form.event_date || saveMutation.isPending}
                >
                  {saveMutation.isPending ? t('hr.common.saving') : t('hr.common.save')}
                </Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      </div>

      <div className="bg-card rounded-2xl border overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t('hr.pages.history.table.date')}</TableHead>
              <TableHead>{t('hr.pages.history.table.employee')}</TableHead>
              <TableHead>
                <div className="flex items-center gap-2">
                  <span>{t('hr.pages.history.table.eventType')}</span>
                  {filterType !== 'all' && (
                    <button type="button" className="text-xs text-muted-foreground hover:underline" onClick={() => setFilterType('all')}>
                      {t(`hr.pages.history.eventTypes.${filterType}`)} ×
                    </button>
                  )}
                </div>
              </TableHead>
              <TableHead>{t('hr.pages.history.table.details')}</TableHead>
              <TableHead>{t('hr.pages.history.table.orderNumber')}</TableHead>
              <TableHead className="text-right">{t('hr.pages.history.table.actions')}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filteredRecords.map((rec) => {
              let detail = '';
              if (rec.event_type === 'hired') {
                detail = [rec.to_department_name, rec.to_position_title].filter(Boolean).join(' / ') || '—';
              } else if (rec.event_type === 'dismissed') {
                detail = rec.comment || '—';
              } else {
                const from = [rec.from_department_name, rec.from_position_title].filter(Boolean).join(' / ');
                const to = [rec.to_department_name, rec.to_position_title].filter(Boolean).join(' / ');
                detail = from && to ? `${from} → ${to}` : to || from || '—';
              }

              return (
                <TableRow key={rec.id}>
                  <TableCell>{new Date(rec.event_date).toLocaleDateString()}</TableCell>
                  <TableCell className="font-medium">{rec.employee_name}</TableCell>
                  <TableCell>
                    <button type="button" onClick={() => setFilterType((prev) => prev === rec.event_type ? 'all' : rec.event_type)}>
                      <Badge className={EVENT_COLORS[rec.event_type] || 'bg-gray-500'}>
                        {t(`hr.pages.history.eventTypes.${rec.event_type}`)}
                      </Badge>
                    </button>
                  </TableCell>
                  <TableCell className="max-w-[300px] truncate">{detail}</TableCell>
                  <TableCell>{rec.order_number || '—'}</TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end gap-2">
                      <Button size="sm" variant="outline" onClick={() => startEdit(rec)}>{t('hr.common.edit')}</Button>
                      {isSenior && (
                        <Button
                          size="sm"
                          variant="destructive"
                          onClick={() => {
                            if (confirm(t('hr.pages.history.deleteConfirm'))) deleteMutation.mutate(rec.id);
                          }}
                        >
                          {t('hr.common.delete')}
                        </Button>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
    </HRLayout>
  );
};

export default HRHistory;
