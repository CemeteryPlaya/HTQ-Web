import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import api from '@/api/client';
import { Plus } from 'lucide-react';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useHRLevel } from '@/hooks/useHRLevel';

interface Vacancy {
  id: number;
  title: string;
  department: number | null;
  department_name: string;
  status: string;
  created_by_name: string;
  applications_count: number;
  salary_min: number | null;
  salary_max: number | null;
  created_at: string;
  description?: string;
  requirements?: string;
}

interface Department {
  id: number;
  name: string;
}

const HRVacancies = () => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { isSenior } = useHRLevel();
  const { data: vacancies, isLoading, error } = useQuery({
    queryKey: ['hr-vacancies'],
    queryFn: async () => {
      const res = await api.get<Vacancy[]>('hr/v1/vacancies/');
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

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<Vacancy | null>(null);
  const [form, setForm] = useState({
    title: '',
    department: 'none',
    description: '',
    requirements: '',
    salary_min: '',
    salary_max: '',
    status: 'open',
  });

  const saveMutation = useMutation({
    mutationFn: async () => {
      const payload: any = {
        title: form.title,
        department: form.department === 'none' ? null : Number(form.department),
        description: form.description || '',
        requirements: form.requirements || '',
        salary_min: form.salary_min ? Number(form.salary_min) : null,
        salary_max: form.salary_max ? Number(form.salary_max) : null,
        status: form.status,
      };
      if (editing) {
        const res = await api.put(`hr/v1/vacancies/${editing.id}/`, payload);
        return res.data;
      }
      const res = await api.post('hr/v1/vacancies/', payload);
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hr-vacancies'] });
      setDialogOpen(false);
      setEditing(null);
      setForm({
        title: '',
        department: 'none',
        description: '',
        requirements: '',
        salary_min: '',
        salary_max: '',
        status: 'open',
      });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`hr/v1/vacancies/${id}/`);
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['hr-vacancies'] }),
  });

  const startCreate = () => {
    setEditing(null);
    setForm({
      title: '',
      department: 'none',
      description: '',
      requirements: '',
      salary_min: '',
      salary_max: '',
      status: 'open',
    });
    setDialogOpen(true);
  };

  const startEdit = (vacancy: Vacancy) => {
    setEditing(vacancy);
    setForm({
      title: vacancy.title || '',
      department: vacancy.department ? String(vacancy.department) : 'none',
      description: vacancy.description || '',
      requirements: vacancy.requirements || '',
      salary_min: vacancy.salary_min ? String(vacancy.salary_min) : '',
      salary_max: vacancy.salary_max ? String(vacancy.salary_max) : '',
      status: vacancy.status || 'open',
    });
    setDialogOpen(true);
  };

  const statusLabels: Record<string, string> = {
    open: t('hr.pages.vacancies.status.open'),
    closed: t('hr.pages.vacancies.status.closed'),
    on_hold: t('hr.pages.vacancies.status.onHold'),
  };

  if (isLoading) {
    return (
      <div className="rounded-2xl border bg-card/70 p-8 text-center">{t('hr.common.loading')}</div>
    );
  }
  if (error) {
    return (
      <div className="rounded-2xl border bg-card/70 p-8 text-center text-red-500">
        {t('hr.pages.vacancies.error')}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div className="text-sm text-muted-foreground">{t('hr.common.total')}: {vacancies?.length || 0}</div>
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button onClick={startCreate} className="gap-2">
              <Plus className="h-4 w-4" />
              {t('hr.pages.vacancies.actions.add')}
            </Button>
          </DialogTrigger>
          <DialogContent className="max-w-2xl">
            <DialogHeader>
              <DialogTitle>{editing ? t('hr.pages.vacancies.edit') : t('hr.pages.vacancies.new')}</DialogTitle>
            </DialogHeader>
            <div className="grid gap-4">
              <label className="grid gap-2 text-sm">
                {t('hr.pages.vacancies.fields.title')}
                <Input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
              </label>
              <label className="grid gap-2 text-sm">
                {t('hr.pages.vacancies.fields.department')}
                <Select value={form.department} onValueChange={(value) => setForm({ ...form, department: value })}>
                  <SelectTrigger>
                    <SelectValue placeholder={t('hr.pages.vacancies.placeholders.selectDepartment')} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">{t('hr.common.noDepartment')}</SelectItem>
                    {departments?.map((dept) => (
                      <SelectItem key={dept.id} value={String(dept.id)}>
                        {dept.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </label>
              <label className="grid gap-2 text-sm">
                {t('hr.pages.vacancies.fields.status')}
                <Select value={form.status} onValueChange={(value) => setForm({ ...form, status: value })}>
                  <SelectTrigger>
                    <SelectValue placeholder={t('hr.pages.vacancies.placeholders.selectStatus')} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="open">{t('hr.pages.vacancies.status.open')}</SelectItem>
                    <SelectItem value="closed">{t('hr.pages.vacancies.status.closed')}</SelectItem>
                    <SelectItem value="on_hold">{t('hr.pages.vacancies.status.onHold')}</SelectItem>
                  </SelectContent>
                </Select>
              </label>
              {isSenior && (
                <div className="grid gap-4 md:grid-cols-2">
                  <label className="grid gap-2 text-sm">
                    {t('hr.pages.vacancies.fields.salaryMin')}
                    <Input type="number" value={form.salary_min} onChange={(e) => setForm({ ...form, salary_min: e.target.value })} />
                  </label>
                  <label className="grid gap-2 text-sm">
                    {t('hr.pages.vacancies.fields.salaryMax')}
                    <Input type="number" value={form.salary_max} onChange={(e) => setForm({ ...form, salary_max: e.target.value })} />
                  </label>
                </div>
              )}
              <label className="grid gap-2 text-sm">
                {t('hr.pages.vacancies.fields.description')}
                <Textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
              </label>
              <label className="grid gap-2 text-sm">
                {t('hr.pages.vacancies.fields.requirements')}
                <Textarea value={form.requirements} onChange={(e) => setForm({ ...form, requirements: e.target.value })} />
              </label>
              <div className="flex justify-end gap-2">
                <Button variant="outline" onClick={() => setDialogOpen(false)}>{t('hr.common.cancel')}</Button>
                <Button onClick={() => saveMutation.mutate()} disabled={!form.title || saveMutation.isPending}>
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
              <TableHead>{t('hr.pages.vacancies.table.title')}</TableHead>
              <TableHead>{t('hr.pages.vacancies.table.department')}</TableHead>
              <TableHead>{t('hr.pages.vacancies.table.status')}</TableHead>
              {isSenior && <TableHead>{t('hr.pages.vacancies.table.salaryRange')}</TableHead>}
              <TableHead>{t('hr.pages.vacancies.table.applications')}</TableHead>
              <TableHead>{t('hr.pages.vacancies.table.created')}</TableHead>
              <TableHead className="text-right">{t('hr.pages.vacancies.table.actions')}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {vacancies?.map((vacancy) => (
              <TableRow key={vacancy.id}>
                <TableCell className="font-medium">{vacancy.title}</TableCell>
                <TableCell>{vacancy.department_name || '—'}</TableCell>
                <TableCell>
                  <Badge variant={vacancy.status === 'open' ? 'default' : 'secondary'}>
                    {statusLabels[vacancy.status] || vacancy.status}
                  </Badge>
                </TableCell>
                {isSenior && (
                  <TableCell>
                    {vacancy.salary_min && vacancy.salary_max
                      ? t('hr.pages.vacancies.salaryRange', { min: vacancy.salary_min, max: vacancy.salary_max })
                      : '—'}
                  </TableCell>
                )}
                <TableCell>{vacancy.applications_count || 0}</TableCell>
                <TableCell>{new Date(vacancy.created_at).toLocaleDateString()}</TableCell>
                <TableCell className="text-right">
                  <div className="flex justify-end gap-2">
                    <Button size="sm" variant="outline" onClick={() => startEdit(vacancy)}>{t('hr.common.edit')}</Button>
                    {isSenior && (
                      <Button
                        size="sm"
                        variant="destructive"
                        onClick={() => {
                          if (confirm(t('hr.pages.vacancies.deleteConfirm'))) {
                            deleteMutation.mutate(vacancy.id);
                          }
                        }}
                      >
                        {t('hr.common.delete')}
                      </Button>
                    )}
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
};

export default HRVacancies;
