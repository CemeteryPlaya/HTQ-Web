import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import api from '@/api/client';
import HRLayout from '@/components/hr/HRLayout';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useHRLevel } from '@/hooks/useHRLevel';

interface Document {
  id: number;
  employee: number;
  employee_name: string;
  application?: number | null;
  title: string;
  doc_type: string;
  file: string;
  uploaded_by_name: string;
  created_at: string;
  description?: string;
}

interface EmployeeOption {
  id: number;
  full_name: string;
}

const HRDocuments = () => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { isSenior } = useHRLevel();
  const { data: documents, isLoading, error } = useQuery({
    queryKey: ['hr-documents'],
    queryFn: async () => {
      const res = await api.get<Document[]>('hr/v1/documents/');
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

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<Document | null>(null);
  const [form, setForm] = useState({
    employee: 'none',
    title: '',
    doc_type: 'other',
    description: '',
    file: null as File | null,
  });
  const [pdfFields, setPdfFields] = useState({
    candidate_name: '',
    candidate_email: '',
    vacancy_title: '',
    department_name: '',
    hire_date: '',
    work_conditions: '',
    work_type: '',
    probation_period: '',
    work_schedule: '',
  });
  const [pdfFieldsLoading, setPdfFieldsLoading] = useState(false);

  const saveMutation = useMutation({
    mutationFn: async () => {
      const formData = new FormData();
      if (form.employee !== 'none') formData.append('employee', form.employee);
      formData.append('title', form.title);
      formData.append('doc_type', form.doc_type);
      formData.append('description', form.description || '');
      if (form.file) formData.append('file', form.file);

      if (editing) {
        const res = await api.put(`hr/v1/documents/${editing.id}/`, formData, {
          headers: { 'Content-Type': 'multipart/form-data' },
        });
        return res.data;
      }
      const res = await api.post('hr/v1/documents/', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hr-documents'] });
      queryClient.invalidateQueries({ queryKey: ['hr-archive'] });
      setDialogOpen(false);
      setEditing(null);
      setForm({ employee: 'none', title: '', doc_type: 'other', description: '', file: null });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`hr/v1/documents/${id}/`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hr-documents'] });
      queryClient.invalidateQueries({ queryKey: ['hr-archive'] });
    },
  });

  const regenerateMutation = useMutation({
    mutationFn: async (args: { docId: number; fields: typeof pdfFields }) => {
      const res = await api.post(`hr/v1/documents/${args.docId}/regenerate/`, args.fields);
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hr-documents'] });
      queryClient.invalidateQueries({ queryKey: ['hr-archive'] });
      setDialogOpen(false);
      setEditing(null);
    },
  });

  const startCreate = () => {
    setEditing(null);
    setForm({ employee: 'none', title: '', doc_type: 'other', description: '', file: null });
    setDialogOpen(true);
  };

  const startEdit = (doc: Document) => {
    setEditing(doc);
    setForm({
      employee: doc.employee ? String(doc.employee) : 'none',
      title: doc.title || '',
      doc_type: doc.doc_type || 'other',
      description: doc.description || '',
      file: null,
    });
    setDialogOpen(true);
    // Загрузить поля PDF если документ привязан к заявке
    if (doc.application && (doc.doc_type === 'contract' || doc.doc_type === 'order')) {
      setPdfFieldsLoading(true);
      api.get(`hr/v1/documents/${doc.id}/pdf-fields/`).then((res) => {
        setPdfFields(res.data);
      }).catch(() => { }).finally(() => setPdfFieldsLoading(false));
    }
  };

  const docTypeLabels: Record<string, string> = {
    contract: t('hr.pages.documents.docTypes.contract'),
    amendment: t('hr.pages.documents.docTypes.amendment'),
    order: t('hr.pages.documents.docTypes.order'),
    certificate: t('hr.pages.documents.docTypes.certificate'),
    other: t('hr.pages.documents.docTypes.other'),
  };

  if (isLoading) {
    return (
      <HRLayout title={t('hr.pages.documents.title')} subtitle={t('hr.pages.documents.subtitle')}>
        <div className="rounded-2xl border bg-card/70 p-8 text-center">{t('hr.common.loading')}</div>
      </HRLayout>
    );
  }
  if (error) {
    return (
      <HRLayout title={t('hr.pages.documents.title')} subtitle={t('hr.pages.documents.subtitle')}>
        <div className="rounded-2xl border bg-card/70 p-8 text-center text-red-500">
          {t('hr.pages.documents.error')}
        </div>
      </HRLayout>
    );
  }

  return (
    <HRLayout title={t('hr.pages.documents.title')} subtitle={t('hr.pages.documents.subtitle')}>
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div className="text-sm text-muted-foreground">{t('hr.common.total')}: {documents?.length || 0}</div>
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button onClick={startCreate}>{t('hr.pages.documents.upload')}</Button>
          </DialogTrigger>
          <DialogContent className="max-w-2xl">
            <DialogHeader>
              <DialogTitle>{editing ? t('hr.pages.documents.edit') : t('hr.pages.documents.new')}</DialogTitle>
            </DialogHeader>
            <div className="grid gap-4">
              <label className="grid gap-2 text-sm">
                {t('hr.pages.documents.fields.employee')}
                <Select value={form.employee} onValueChange={(value) => setForm({ ...form, employee: value })}>
                  <SelectTrigger>
                    <SelectValue placeholder={t('hr.pages.documents.placeholders.selectEmployee')} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">{t('hr.pages.documents.placeholders.selectEmployee')}</SelectItem>
                    {employees?.map((emp) => (
                      <SelectItem key={emp.id} value={String(emp.id)}>
                        {emp.full_name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </label>

              <div className="grid gap-4 md:grid-cols-2">
                <label className="grid gap-2 text-sm">
                  {t('hr.pages.documents.fields.title')}
                  <Input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
                </label>
                <label className="grid gap-2 text-sm">
                  {t('hr.pages.documents.fields.type')}
                  <Select value={form.doc_type} onValueChange={(value) => setForm({ ...form, doc_type: value })}>
                    <SelectTrigger>
                      <SelectValue placeholder={t('hr.pages.documents.placeholders.selectType')} />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="contract">{t('hr.pages.documents.docTypes.contract')}</SelectItem>
                      <SelectItem value="amendment">{t('hr.pages.documents.docTypes.amendment')}</SelectItem>
                      <SelectItem value="order">{t('hr.pages.documents.docTypes.order')}</SelectItem>
                      <SelectItem value="certificate">{t('hr.pages.documents.docTypes.certificate')}</SelectItem>
                      <SelectItem value="other">{t('hr.pages.documents.docTypes.other')}</SelectItem>
                    </SelectContent>
                  </Select>
                </label>
              </div>

              <label className="grid gap-2 text-sm">
                {t('hr.pages.documents.fields.description')}
                <Textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
              </label>

              <label className="grid gap-2 text-sm">
                {t('hr.pages.documents.fields.file')}
                <Input type="file" onChange={(e: any) => setForm({ ...form, file: e.target.files?.[0] || null })} />
              </label>

              {editing && (editing.doc_type === 'contract' || editing.doc_type === 'order') && editing.application && (
                <div className="rounded-lg border border-dashed p-4 space-y-3">
                  <p className="text-sm font-medium">{t('hr.pages.archive.editDialog.regenerateHint')}</p>
                  {pdfFieldsLoading ? (
                    <p className="text-sm text-muted-foreground">{t('hr.common.loading')}</p>
                  ) : (
                    <>
                      <div className="grid gap-3 md:grid-cols-2">
                        <label className="grid gap-1 text-sm">
                          {t('hr.pages.archive.editDialog.fields.candidateName')}
                          <Input value={pdfFields.candidate_name} onChange={(e) => setPdfFields({ ...pdfFields, candidate_name: e.target.value })} />
                        </label>
                        <label className="grid gap-1 text-sm">
                          {t('hr.pages.archive.editDialog.fields.candidateEmail')}
                          <Input value={pdfFields.candidate_email} onChange={(e) => setPdfFields({ ...pdfFields, candidate_email: e.target.value })} />
                        </label>
                        <label className="grid gap-1 text-sm">
                          {t('hr.pages.archive.editDialog.fields.vacancyTitle')}
                          <Input value={pdfFields.vacancy_title} onChange={(e) => setPdfFields({ ...pdfFields, vacancy_title: e.target.value })} />
                        </label>
                        <label className="grid gap-1 text-sm">
                          {t('hr.pages.archive.editDialog.fields.departmentName')}
                          <Input value={pdfFields.department_name} onChange={(e) => setPdfFields({ ...pdfFields, department_name: e.target.value })} />
                        </label>
                        <label className="grid gap-1 text-sm">
                          {t('hr.pages.archive.editDialog.fields.hireDate')}
                          <Input type="date" value={pdfFields.hire_date} onChange={(e) => setPdfFields({ ...pdfFields, hire_date: e.target.value })} />
                        </label>
                        <label className="grid gap-1 text-sm">
                          {t('hr.pages.archive.editDialog.fields.workConditions')}
                          <Input value={pdfFields.work_conditions} onChange={(e) => setPdfFields({ ...pdfFields, work_conditions: e.target.value })} />
                        </label>
                        <label className="grid gap-1 text-sm">
                          {t('hr.pages.archive.editDialog.fields.workType')}
                          <Input value={pdfFields.work_type} onChange={(e) => setPdfFields({ ...pdfFields, work_type: e.target.value })} />
                        </label>
                        <label className="grid gap-1 text-sm">
                          {t('hr.pages.archive.editDialog.fields.probationPeriod')}
                          <Input value={pdfFields.probation_period} onChange={(e) => setPdfFields({ ...pdfFields, probation_period: e.target.value })} />
                        </label>
                        {editing.doc_type === 'contract' && (
                          <label className="grid gap-1 text-sm">
                            {t('hr.pages.archive.editDialog.fields.workSchedule')}
                            <Input value={pdfFields.work_schedule} onChange={(e) => setPdfFields({ ...pdfFields, work_schedule: e.target.value })} />
                          </label>
                        )}
                      </div>
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => editing && regenerateMutation.mutate({ docId: editing.id, fields: pdfFields })}
                        disabled={regenerateMutation.isPending}
                      >
                        {regenerateMutation.isPending
                          ? t('hr.common.saving')
                          : t('hr.pages.archive.editDialog.regenerate')}
                      </Button>
                    </>
                  )}
                </div>
              )}

              <div className="flex justify-end gap-2">
                <Button variant="outline" onClick={() => setDialogOpen(false)}>{t('hr.common.cancel')}</Button>
                <Button onClick={() => saveMutation.mutate()} disabled={form.employee === 'none' || !form.title || saveMutation.isPending}>
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
              <TableHead>{t('hr.pages.documents.table.employee')}</TableHead>
              <TableHead>{t('hr.pages.documents.table.document')}</TableHead>
              <TableHead>{t('hr.pages.documents.table.type')}</TableHead>
              <TableHead>{t('hr.pages.documents.table.uploadedBy')}</TableHead>
              <TableHead>{t('hr.pages.documents.table.date')}</TableHead>
              <TableHead>{t('hr.pages.documents.table.actions')}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {documents?.map((doc) => (
              <TableRow key={doc.id}>
                <TableCell className="font-medium">{doc.employee_name}</TableCell>
                <TableCell>{doc.title}</TableCell>
                <TableCell>{docTypeLabels[doc.doc_type] || doc.doc_type}</TableCell>
                <TableCell>{doc.uploaded_by_name || '—'}</TableCell>
                <TableCell>{new Date(doc.created_at).toLocaleDateString()}</TableCell>
                <TableCell>
                  <div className="flex items-center gap-2">
                    <a href={doc.file} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">
                      {t('hr.common.download')}
                    </a>
                    <Button size="sm" variant="outline" onClick={() => startEdit(doc)}>{t('hr.common.edit')}</Button>
                    {isSenior && (
                      <Button
                        size="sm"
                        variant="destructive"
                        onClick={() => {
                          if (confirm(t('hr.pages.documents.deleteConfirm'))) {
                            deleteMutation.mutate(doc.id);
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
    </HRLayout>
  );
};

export default HRDocuments;
