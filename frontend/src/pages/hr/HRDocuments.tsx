import React, { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import api from '@/api/client';
import { mediaApi } from '@/api/media';
import HRLayout from '@/components/hr/HRLayout';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { useHRLevel } from '@/hooks/useHRLevel';
import { reportApiError } from '@/lib/apiError';

/**
 * Форма ответа `GET /api/hr/v1/documents/` (apps.hr.services.document_service
 * ::serialize). Имён сотрудника/загрузившего и ссылки на файл бэкенд НЕ
 * отдаёт — id разворачиваются в имена по списку сотрудников, а файл лежит
 * в media (`metadata.media_file_id`).
 */
interface HRDocument {
  id: number;
  employee_id: number;
  title: string;
  doc_type: string;
  file_path: string;
  file_size: number;
  mime_type: string;
  metadata?: {
    media_file_id?: string;
    original_filename?: string;
    description?: string;
    uploaded_by_user_id?: number;
  } | null;
  /** null — грузила платформенная учётка без карточки сотрудника. */
  uploaded_by: number | null;
  created_at: string;
  updated_at: string;
}

interface EmployeeOption {
  id: number;
  first_name: string;
  last_name: string;
  middle_name?: string | null;
  email?: string | null;
}

const employeeName = (emp?: EmployeeOption): string => {
  if (!emp) return '';
  const full = [emp.last_name, emp.first_name, emp.middle_name].filter(Boolean).join(' ').trim();
  return full || emp.email || `#${emp.id}`;
};

const HRDocuments = () => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { isSenior } = useHRLevel();

  const { data: documents, isLoading, error } = useQuery({
    queryKey: ['hr-documents'],
    queryFn: async () => {
      const res = await api.get<HRDocument[]>('hr/v1/documents/');
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

  const employeeById = useMemo(() => {
    const map = new Map<number, EmployeeOption>();
    (employees || []).forEach((emp) => map.set(emp.id, emp));
    return map;
  }, [employees]);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [form, setForm] = useState({
    employee: 'none',
    title: '',
    doc_type: 'other',
    description: '',
    file: null as File | null,
  });

  const resetForm = () =>
    setForm({ employee: 'none', title: '', doc_type: 'other', description: '', file: null });

  const uploadMutation = useMutation({
    mutationFn: async () => {
      // multipart: файл уезжает в apps.media_files, карточка документа
      // создаётся тем же запросом (views.py::_upload_document_multipart).
      const formData = new FormData();
      formData.append('employee', form.employee);
      formData.append('title', form.title);
      formData.append('doc_type', form.doc_type);
      formData.append('description', form.description || '');
      if (form.file) formData.append('file', form.file);

      const res = await api.post('hr/v1/documents/', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hr-documents'] });
      queryClient.invalidateQueries({ queryKey: ['hr-archive'] });
      setDialogOpen(false);
      resetForm();
    },
    onError: (err) => reportApiError(err, t('hr.common.unknownError')),
  });

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`hr/v1/documents/${id}/`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hr-documents'] });
      queryClient.invalidateQueries({ queryKey: ['hr-archive'] });
    },
    onError: (err) => reportApiError(err, t('hr.common.unknownError')),
  });

  /**
   * Файл приватный: media отдаёт его только с JWT, поэтому обычная ссылка
   * не подходит — качаем через axios и отдаём браузеру blob.
   */
  const downloadMutation = useMutation({
    mutationFn: async (doc: HRDocument) => {
      const fileId = doc.metadata?.media_file_id;
      if (!fileId) throw new Error('missing media_file_id');
      const res = await mediaApi.download(fileId);
      const url = URL.createObjectURL(res.data as Blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = doc.metadata?.original_filename || doc.title || 'document';
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    },
    onError: (err) => reportApiError(err, t('hr.common.unknownError')),
  });

  const startCreate = () => {
    resetForm();
    setDialogOpen(true);
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
        <Dialog
          open={dialogOpen}
          onOpenChange={(open) => {
            setDialogOpen(open);
            if (!open) resetForm();
          }}
        >
          <DialogTrigger asChild>
            <Button onClick={startCreate}>{t('hr.pages.documents.upload')}</Button>
          </DialogTrigger>
          <DialogContent className="max-w-2xl">
            <DialogHeader>
              <DialogTitle>{t('hr.pages.documents.new')}</DialogTitle>
              {/* Radix требует описание (или aria-describedby) — без него
                  DialogContent ругается в консоли и теряет доступность. */}
              <DialogDescription>{t('hr.pages.documents.subtitle')}</DialogDescription>
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
                        {employeeName(emp)}
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
                {/* Скоуп hr_doc в media — PDF-only, до 25 МБ, с проверкой
                    сигнатуры файла (media_files/services/scope_policy.py). */}
                <Input
                  type="file"
                  accept="application/pdf"
                  onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                    setForm({ ...form, file: e.target.files?.[0] || null })
                  }
                />
                <span className="text-xs text-muted-foreground">
                  {t('hr.pages.documents.fileHint', 'Только PDF, до 25 МБ')}
                </span>
              </label>

              <div className="flex justify-end gap-2">
                <Button variant="outline" onClick={() => setDialogOpen(false)}>{t('hr.common.cancel')}</Button>
                <Button
                  onClick={() => uploadMutation.mutate()}
                  disabled={
                    form.employee === 'none' || !form.title || !form.file || uploadMutation.isPending
                  }
                >
                  {uploadMutation.isPending ? t('hr.common.saving') : t('hr.common.save')}
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
                <TableCell className="font-medium">
                  {employeeName(employeeById.get(doc.employee_id)) || `#${doc.employee_id}`}
                </TableCell>
                <TableCell>
                  <div>{doc.title}</div>
                  {doc.metadata?.description && (
                    <div className="text-xs text-muted-foreground">{doc.metadata.description}</div>
                  )}
                </TableCell>
                <TableCell>{docTypeLabels[doc.doc_type] || doc.doc_type}</TableCell>
                <TableCell>
                  {(doc.uploaded_by != null && employeeName(employeeById.get(doc.uploaded_by))) || '—'}
                </TableCell>
                <TableCell>{new Date(doc.created_at).toLocaleDateString()}</TableCell>
                <TableCell>
                  <div className="flex items-center gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => downloadMutation.mutate(doc)}
                      disabled={!doc.metadata?.media_file_id || downloadMutation.isPending}
                    >
                      {t('hr.common.download')}
                    </Button>
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
