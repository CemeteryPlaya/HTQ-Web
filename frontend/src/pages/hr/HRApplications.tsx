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
import { PhoneInput } from '@/components/ui/phone-input';
import { Textarea } from '@/components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useHRLevel } from '@/hooks/useHRLevel';

interface Application {
  id: number;
  vacancy: number;
  first_name: string;
  last_name: string;
  email: string;
  phone: string;
  vacancy_title: string;
  status: 'new' | 'reviewed' | 'interview' | 'offered' | 'rejected' | 'hired';
  created_at: string;
  notes?: string;
  resume?: string | null;
  cover_letter?: string;
}

interface Vacancy {
  id: number;
  title: string;
}

const HRApplications = () => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { isSenior } = useHRLevel();
  const { data: applications, isLoading, error } = useQuery({
    queryKey: ['hr-applications'],
    queryFn: async () => {
      const res = await api.get<Application[]>('hr/v1/applications/');
      return res.data;
    },
  });

  const { data: vacancies } = useQuery({
    queryKey: ['hr-vacancies'],
    queryFn: async () => {
      const res = await api.get<Vacancy[]>('hr/v1/vacancies/');
      return res.data;
    },
  });

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<Application | null>(null);
  const [form, setForm] = useState({
    vacancy: 'none',
    first_name: '',
    last_name: '',
    email: '',
    phone: '',
    notes: '',
    cover_letter: '',
    resume: null as File | null,
  });

  const saveMutation = useMutation({
    mutationFn: async () => {
      const formData = new FormData();
      if (form.vacancy !== 'none') formData.append('vacancy', form.vacancy);
      formData.append('first_name', form.first_name);
      formData.append('last_name', form.last_name);
      formData.append('email', form.email);
      formData.append('phone', form.phone || '');
      formData.append('notes', form.notes || '');
      formData.append('cover_letter', form.cover_letter || '');
      if (form.resume) formData.append('resume', form.resume);

      if (editing) {
        const res = await api.patch(`hr/v1/applications/${editing.id}/`, formData, {
          headers: { 'Content-Type': 'multipart/form-data' },
        });
        return res.data;
      }
      const res = await api.post('hr/v1/applications/', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hr-applications'] });
      setDialogOpen(false);
      setEditing(null);
      setForm({
        vacancy: 'none',
        first_name: '',
        last_name: '',
        email: '',
        phone: '',
        notes: '',
        cover_letter: '',
        resume: null,
      });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`hr/v1/applications/${id}/`);
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['hr-applications'] }),
  });

  const startCreate = () => {
    setEditing(null);
    setForm({
      vacancy: 'none',
      first_name: '',
      last_name: '',
      email: '',
      phone: '',
      notes: '',
      cover_letter: '',
      resume: null,
    });
    setDialogOpen(true);
  };

  const startEdit = (app: Application) => {
    setEditing(app);
    setForm({
      vacancy: app.vacancy ? String(app.vacancy) : 'none',
      first_name: app.first_name || '',
      last_name: app.last_name || '',
      email: app.email || '',
      phone: app.phone || '',
      notes: app.notes || '',
      cover_letter: app.cover_letter || '',
      resume: null,
    });
    setDialogOpen(true);
  };

  const prevStatusMap: Record<Application['status'], Application['status'] | null> = {
    new: null,
    reviewed: 'new',
    interview: 'reviewed',
    offered: 'interview',
    hired: null,
    rejected: null,
  };

  const nextStatusMap: Record<Application['status'], Application['status'] | null> = {
    new: 'reviewed',
    reviewed: 'interview',
    interview: 'offered',
    offered: null,
    hired: null,
    rejected: null,
  };

  const stageMutation = useMutation({
    mutationFn: async ({ id, status }: { id: number; status: Application['status'] }) => {
      const res = await api.patch(`hr/v1/applications/${id}/`, { status });
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hr-applications'] });
      queryClient.invalidateQueries({ queryKey: ['hr-offers'] });
    },
  });

  const statusLabels: Record<string, string> = {
    new: t('hr.pages.applications.status.new'),
    reviewed: t('hr.pages.applications.status.reviewed'),
    interview: t('hr.pages.applications.status.interview'),
    offered: t('hr.pages.applications.status.offered'),
    rejected: t('hr.pages.applications.status.rejected'),
    hired: t('hr.pages.applications.status.hired'),
  };

  if (isLoading) {
    return (
      <div className="rounded-2xl border bg-card/70 p-8 text-center">{t('hr.common.loading')}</div>
    );
  }
  if (error) {
    return (
      <div className="rounded-2xl border bg-card/70 p-8 text-center text-red-500">
        {t('hr.pages.applications.error')}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div className="text-sm text-muted-foreground">{t('hr.common.total')}: {applications?.length || 0}</div>
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button onClick={startCreate} className="gap-2">
              <Plus className="h-4 w-4" />
              {t('hr.pages.applications.add')}
            </Button>
          </DialogTrigger>
          <DialogContent className="max-w-2xl">
            <DialogHeader>
              <DialogTitle>{editing ? t('hr.pages.applications.edit') : t('hr.pages.applications.new')}</DialogTitle>
            </DialogHeader>
            <div className="grid gap-4">
              <label className="grid gap-2 text-sm">
                {t('hr.pages.applications.fields.vacancy')}
                <Select value={form.vacancy} onValueChange={(value) => setForm({ ...form, vacancy: value })}>
                  <SelectTrigger>
                    <SelectValue placeholder={t('hr.pages.applications.placeholders.selectVacancy')} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">{t('hr.pages.applications.placeholders.selectVacancy')}</SelectItem>
                    {vacancies?.map((vacancy) => (
                      <SelectItem key={vacancy.id} value={String(vacancy.id)}>
                        {vacancy.title}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </label>

              <div className="grid gap-4 md:grid-cols-2">
                <label className="grid gap-2 text-sm">
                  {t('hr.pages.applications.fields.firstName')}
                  <Input value={form.first_name} onChange={(e) => setForm({ ...form, first_name: e.target.value })} />
                </label>
                <label className="grid gap-2 text-sm">
                  {t('hr.pages.applications.fields.lastName')}
                  <Input value={form.last_name} onChange={(e) => setForm({ ...form, last_name: e.target.value })} />
                </label>
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <label className="grid gap-2 text-sm">
                  {t('hr.pages.applications.fields.email')}
                  <Input value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
                </label>
                <label className="grid gap-2 text-sm">
                  {t('hr.pages.applications.fields.phone')}
                  <PhoneInput value={form.phone} onChange={(v) => setForm({ ...form, phone: v })} />
                </label>
              </div>

              <label className="grid gap-2 text-sm">
                {t('hr.pages.applications.fields.coverLetter')}
                <Textarea value={form.cover_letter} onChange={(e) => setForm({ ...form, cover_letter: e.target.value })} />
              </label>

              <label className="grid gap-2 text-sm">
                {t('hr.pages.applications.fields.notes')}
                <Textarea value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
              </label>

              <label className="grid gap-2 text-sm">
                {t('hr.pages.applications.fields.resume')}
                <Input type="file" onChange={(e: any) => setForm({ ...form, resume: e.target.files?.[0] || null })} />
              </label>

              <div className="flex justify-end gap-2">
                <Button variant="outline" onClick={() => setDialogOpen(false)}>{t('hr.common.cancel')}</Button>
                <Button onClick={() => saveMutation.mutate()} disabled={form.vacancy === 'none' || !form.email || saveMutation.isPending}>
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
              <TableHead>{t('hr.pages.applications.table.applicant')}</TableHead>
              <TableHead>{t('hr.pages.applications.table.email')}</TableHead>
              <TableHead>{t('hr.pages.applications.table.phone')}</TableHead>
              <TableHead>{t('hr.pages.applications.table.vacancy')}</TableHead>
              <TableHead>{t('hr.pages.applications.table.status')}</TableHead>
              <TableHead>{t('hr.pages.applications.table.applied')}</TableHead>
              <TableHead className="text-right">{t('hr.pages.applications.table.actions')}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {applications?.map((app) => (
              <TableRow key={app.id}>
                <TableCell className="font-medium">{app.first_name} {app.last_name}</TableCell>
                <TableCell>{app.email}</TableCell>
                <TableCell>{app.phone || '—'}</TableCell>
                <TableCell>{app.vacancy_title}</TableCell>
                <TableCell>
                  <Badge>{statusLabels[app.status] || app.status}</Badge>
                </TableCell>
                <TableCell>{new Date(app.created_at).toLocaleDateString()}</TableCell>
                <TableCell className="text-right">
                  <div className="flex flex-wrap justify-end gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={!prevStatusMap[app.status] || stageMutation.isPending}
                      onClick={() => {
                        const prevStatus = prevStatusMap[app.status];
                        if (prevStatus) stageMutation.mutate({ id: app.id, status: prevStatus });
                      }}
                    >
                      {t('hr.pages.applications.step.prev')}
                    </Button>
                    <Button
                      size="sm"
                      disabled={!nextStatusMap[app.status] || stageMutation.isPending}
                      onClick={() => {
                        const nextStatus = nextStatusMap[app.status];
                        if (nextStatus) stageMutation.mutate({ id: app.id, status: nextStatus });
                      }}
                    >
                      {t('hr.pages.applications.step.next')}
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => startEdit(app)}>{t('hr.common.edit')}</Button>
                    {isSenior && (
                      <Button
                        size="sm"
                        variant="destructive"
                        onClick={() => {
                          if (confirm(t('hr.pages.applications.deleteConfirm'))) {
                            deleteMutation.mutate(app.id);
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

export default HRApplications;
