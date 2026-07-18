import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import api from '@/api/client';
import HRLayout from '@/components/hr/HRLayout';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { HRArchiveResponse, Application, HRDocument } from '@/types/hr';

type DocSortKey = 'employee' | 'candidate' | 'title' | 'type' | 'status' | 'date' | 'file';

const HRArchive = () => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: ['hr-archive'],
    queryFn: async () => {
      const res = await api.get<HRArchiveResponse>('hr/v1/applications/archive/');
      return res.data;
    },
  });

  const applications = data?.applications ?? [];
  const documents = data?.documents ?? [];

  const [docFilters, setDocFilters] = useState({
    employee: '',
    candidate: '',
    title: '',
    type: 'all',
    status: 'all',
    file: '',
    dateFrom: '',
    dateTo: '',
  });

  const [docSort, setDocSort] = useState<{ key: DocSortKey; direction: 'asc' | 'desc' }>({
    key: 'date',
    direction: 'desc',
  });

  // ── Edit document state ──
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [editingDoc, setEditingDoc] = useState<HRDocument | null>(null);
  const [editForm, setEditForm] = useState({
    title: '',
    doc_type: 'other' as string,
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

  const startEditDoc = (doc: HRDocument) => {
    setEditingDoc(doc);
    setEditForm({
      title: doc.title || '',
      doc_type: doc.doc_type || 'other',
      description: doc.description || '',
      file: null,
    });
    setEditDialogOpen(true);
    // Загрузить поля PDF если документ привязан к заявке
    if (doc.application && (doc.doc_type === 'contract' || doc.doc_type === 'order')) {
      setPdfFieldsLoading(true);
      api.get(`hr/v1/documents/${doc.id}/pdf-fields/`).then((res) => {
        setPdfFields(res.data);
      }).catch(() => { }).finally(() => setPdfFieldsLoading(false));
    }
  };

  const editMutation = useMutation({
    mutationFn: async () => {
      if (!editingDoc) return;
      const formData = new FormData();
      formData.append('employee', String(editingDoc.employee));
      formData.append('title', editForm.title);
      formData.append('doc_type', editForm.doc_type);
      formData.append('description', editForm.description || '');
      if (editForm.file) formData.append('file', editForm.file);
      const res = await api.put(`hr/v1/documents/${editingDoc.id}/`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hr-archive'] });
      queryClient.invalidateQueries({ queryKey: ['hr-documents'] });
      setEditDialogOpen(false);
      setEditingDoc(null);
    },
  });

  const regenerateMutation = useMutation({
    mutationFn: async (args: { docId: number; fields: typeof pdfFields }) => {
      const res = await api.post(`hr/v1/documents/${args.docId}/regenerate/`, args.fields);
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hr-archive'] });
      queryClient.invalidateQueries({ queryKey: ['hr-documents'] });
      setEditDialogOpen(false);
      setEditingDoc(null);
    },
  });

  const statusLabel = (status: Application['status']) => {
    if (status === 'hired') return t('hr.pages.archive.status.hired');
    if (status === 'rejected') return t('hr.pages.archive.status.rejected');
    return status;
  };

  const statusVariant = (status: Application['status']) => {
    if (status === 'hired') return 'default' as const;
    return 'destructive' as const;
  };

  const docTypeLabel = (docType: HRDocument['doc_type']) => {
    if (docType === 'contract') return t('hr.pages.documents.docTypes.contract');
    if (docType === 'order') return t('hr.pages.documents.docTypes.order');
    if (docType === 'amendment') return t('hr.pages.documents.docTypes.amendment');
    if (docType === 'certificate') return t('hr.pages.documents.docTypes.certificate');
    return t('hr.pages.documents.docTypes.other');
  };

  const normalize = (value: string | null | undefined) => (value || '').toLowerCase();
  const matches = (value: string | null | undefined, query: string) =>
    normalize(value).includes(normalize(query));

  const getDateOnly = (value: string) => {
    const dt = new Date(value);
    return new Date(dt.getFullYear(), dt.getMonth(), dt.getDate());
  };

  const inDateRange = (value: string, from: string, to: string) => {
    const dateOnly = getDateOnly(value);
    if (from) {
      const fromDate = new Date(`${from}T00:00:00`);
      if (dateOnly < fromDate) return false;
    }
    if (to) {
      const toDate = new Date(`${to}T23:59:59`);
      if (dateOnly > toDate) return false;
    }
    return true;
  };

  const filteredDocuments = documents.filter((doc) => {
    if (docFilters.employee && !matches(doc.employee_name, docFilters.employee)) return false;
    if (docFilters.candidate && !matches(doc.application_candidate_name, docFilters.candidate)) return false;
    if (docFilters.title && !matches(doc.title, docFilters.title)) return false;
    if (docFilters.file && !matches(doc.file, docFilters.file)) return false;
    if (docFilters.type !== 'all' && doc.doc_type !== docFilters.type) return false;
    if (docFilters.status !== 'all') {
      if (docFilters.status === 'none') {
        if (doc.application_status) return false;
      } else if (doc.application_status !== docFilters.status) {
        return false;
      }
    }
    if ((docFilters.dateFrom || docFilters.dateTo) && !inDateRange(doc.created_at, docFilters.dateFrom, docFilters.dateTo)) {
      return false;
    }
    return true;
  });

  const sortedDocuments = [...filteredDocuments].sort((a, b) => {
    let left = '';
    let right = '';
    if (docSort.key === 'employee') {
      left = a.employee_name || '';
      right = b.employee_name || '';
    } else if (docSort.key === 'candidate') {
      left = a.application_candidate_name || '';
      right = b.application_candidate_name || '';
    } else if (docSort.key === 'title') {
      left = a.title || '';
      right = b.title || '';
    } else if (docSort.key === 'type') {
      left = a.doc_type || '';
      right = b.doc_type || '';
    } else if (docSort.key === 'status') {
      left = a.application_status || '';
      right = b.application_status || '';
    } else if (docSort.key === 'file') {
      left = a.file || '';
      right = b.file || '';
    }

    if (docSort.key === 'date') {
      const leftDate = new Date(a.created_at).getTime();
      const rightDate = new Date(b.created_at).getTime();
      return docSort.direction === 'asc' ? leftDate - rightDate : rightDate - leftDate;
    }

    const result = left.localeCompare(right, undefined, { sensitivity: 'base' });
    return docSort.direction === 'asc' ? result : -result;
  });

  const toggleSort = (key: DocSortKey) => {
    setDocSort((prev) => {
      if (prev.key === key) {
        return { key, direction: prev.direction === 'asc' ? 'desc' : 'asc' };
      }
      return { key, direction: 'asc' };
    });
  };

  const sortIndicator = (key: DocSortKey) => {
    if (docSort.key !== key) return '';
    return docSort.direction === 'asc' ? ' ^' : ' v';
  };

  const resetDocFilters = () => {
    setDocFilters({
      employee: '',
      candidate: '',
      title: '',
      type: 'all',
      status: 'all',
      file: '',
      dateFrom: '',
      dateTo: '',
    });
  };

  if (isLoading) {
    return (
      <HRLayout title={t('hr.pages.archive.title')} subtitle={t('hr.pages.archive.subtitle')}>
        <div className="rounded-2xl border bg-card/70 p-8 text-center">{t('hr.common.loading')}</div>
      </HRLayout>
    );
  }

  if (error) {
    return (
      <HRLayout title={t('hr.pages.archive.title')} subtitle={t('hr.pages.archive.subtitle')}>
        <div className="rounded-2xl border bg-card/70 p-8 text-center text-red-500">
          {t('hr.pages.archive.error')}
        </div>
      </HRLayout>
    );
  }

  return (
    <HRLayout title={t('hr.pages.archive.title')} subtitle={t('hr.pages.archive.subtitle')}>
      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded-xl border bg-card p-4">
          <div className="text-sm text-muted-foreground">{t('hr.pages.archive.counters.applications')}: {applications.length}</div>
        </div>
        <div className="rounded-xl border bg-card p-4">
          <div className="text-sm text-muted-foreground">{t('hr.pages.archive.counters.documents')}: {documents.length}</div>
        </div>
      </div>

      <div className="bg-card rounded-2xl border overflow-x-auto">
        <div className="px-4 pt-4 text-sm font-medium min-w-max">{t('hr.pages.archive.sections.applications')}</div>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t('hr.pages.archive.applications.candidate')}</TableHead>
              <TableHead>{t('hr.pages.archive.applications.email')}</TableHead>
              <TableHead>{t('hr.pages.archive.applications.vacancy')}</TableHead>
              <TableHead>{t('hr.pages.archive.applications.status')}</TableHead>
              <TableHead>{t('hr.pages.archive.applications.updated')}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {applications.length === 0 && (
              <TableRow>
                <TableCell colSpan={5} className="text-center text-muted-foreground py-8">
                  {t('hr.pages.archive.emptyApplications')}
                </TableCell>
              </TableRow>
            )}
            {applications.map((item) => (
              <TableRow key={item.id}>
                <TableCell className="font-medium">{item.first_name} {item.last_name}</TableCell>
                <TableCell>{item.email}</TableCell>
                <TableCell>{item.vacancy_title}</TableCell>
                <TableCell><Badge variant={statusVariant(item.status)}>{statusLabel(item.status)}</Badge></TableCell>
                <TableCell>{new Date(item.updated_at).toLocaleDateString()}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <div className="bg-card rounded-2xl border overflow-x-auto">
        <div className="px-4 pt-4 text-sm font-medium min-w-max">{t('hr.pages.archive.sections.documents')}</div>
        <div className="px-4 pb-4 pt-3">
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <Input
              placeholder={t('hr.pages.archive.documents.employee')}
              value={docFilters.employee}
              onChange={(e) => setDocFilters((prev) => ({ ...prev, employee: e.target.value }))}
            />
            <Input
              placeholder={t('hr.pages.archive.documents.candidate')}
              value={docFilters.candidate}
              onChange={(e) => setDocFilters((prev) => ({ ...prev, candidate: e.target.value }))}
            />
            <Input
              placeholder={t('hr.pages.archive.documents.title')}
              value={docFilters.title}
              onChange={(e) => setDocFilters((prev) => ({ ...prev, title: e.target.value }))}
            />
            <Input
              placeholder={t('hr.pages.archive.documents.file')}
              value={docFilters.file}
              onChange={(e) => setDocFilters((prev) => ({ ...prev, file: e.target.value }))}
            />
            <Select value={docFilters.type} onValueChange={(value) => setDocFilters((prev) => ({ ...prev, type: value }))}>
              <SelectTrigger>
                <SelectValue placeholder={t('hr.pages.archive.documents.type')} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t('hr.pages.archive.filters.all')}</SelectItem>
                <SelectItem value="contract">{t('hr.pages.documents.docTypes.contract')}</SelectItem>
                <SelectItem value="order">{t('hr.pages.documents.docTypes.order')}</SelectItem>
                <SelectItem value="amendment">{t('hr.pages.documents.docTypes.amendment')}</SelectItem>
                <SelectItem value="certificate">{t('hr.pages.documents.docTypes.certificate')}</SelectItem>
                <SelectItem value="other">{t('hr.pages.documents.docTypes.other')}</SelectItem>
              </SelectContent>
            </Select>
            <Select value={docFilters.status} onValueChange={(value) => setDocFilters((prev) => ({ ...prev, status: value }))}>
              <SelectTrigger>
                <SelectValue placeholder={t('hr.pages.archive.documents.status')} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t('hr.pages.archive.filters.all')}</SelectItem>
                <SelectItem value="hired">{t('hr.pages.archive.status.hired')}</SelectItem>
                <SelectItem value="rejected">{t('hr.pages.archive.status.rejected')}</SelectItem>
                <SelectItem value="none">{t('hr.pages.archive.filters.noStatus')}</SelectItem>
              </SelectContent>
            </Select>
            <label className="grid gap-1 text-sm">
              <span className="text-muted-foreground">{t('hr.pages.archive.filters.dateFrom')}</span>
              <Input
                type="date"
                value={docFilters.dateFrom}
                onChange={(e) => setDocFilters((prev) => ({ ...prev, dateFrom: e.target.value }))}
              />
            </label>
            <label className="grid gap-1 text-sm">
              <span className="text-muted-foreground">{t('hr.pages.archive.filters.dateTo')}</span>
              <Input
                type="date"
                value={docFilters.dateTo}
                onChange={(e) => setDocFilters((prev) => ({ ...prev, dateTo: e.target.value }))}
              />
            </label>
          </div>
          <div className="mt-3 flex justify-end">
            <Button variant="outline" size="sm" onClick={resetDocFilters}>
              {t('hr.pages.archive.filters.clear')}
            </Button>
          </div>
        </div>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>
                <button type="button" onClick={() => toggleSort('employee')} className="flex items-center gap-1">
                  {t('hr.pages.archive.documents.employee')}{sortIndicator('employee')}
                </button>
              </TableHead>
              <TableHead>
                <button type="button" onClick={() => toggleSort('candidate')} className="flex items-center gap-1">
                  {t('hr.pages.archive.documents.candidate')}{sortIndicator('candidate')}
                </button>
              </TableHead>
              <TableHead>
                <button type="button" onClick={() => toggleSort('title')} className="flex items-center gap-1">
                  {t('hr.pages.archive.documents.title')}{sortIndicator('title')}
                </button>
              </TableHead>
              <TableHead>
                <button type="button" onClick={() => toggleSort('type')} className="flex items-center gap-1">
                  {t('hr.pages.archive.documents.type')}{sortIndicator('type')}
                </button>
              </TableHead>
              <TableHead>
                <button type="button" onClick={() => toggleSort('status')} className="flex items-center gap-1">
                  {t('hr.pages.archive.documents.status')}{sortIndicator('status')}
                </button>
              </TableHead>
              <TableHead>
                <button type="button" onClick={() => toggleSort('date')} className="flex items-center gap-1">
                  {t('hr.pages.archive.documents.date')}{sortIndicator('date')}
                </button>
              </TableHead>
              <TableHead>
                <button type="button" onClick={() => toggleSort('file')} className="flex items-center gap-1">
                  {t('hr.pages.archive.documents.file')}{sortIndicator('file')}
                </button>
              </TableHead>
              <TableHead>{t('hr.common.actions')}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {sortedDocuments.length === 0 && (
              <TableRow>
                <TableCell colSpan={8} className="text-center text-muted-foreground py-8">
                  {t('hr.pages.archive.emptyDocuments')}
                </TableCell>
              </TableRow>
            )}
            {sortedDocuments.map((doc) => (
              <TableRow key={doc.id}>
                <TableCell className="font-medium">{doc.employee_name}</TableCell>
                <TableCell>{doc.application_candidate_name || '—'}</TableCell>
                <TableCell>{doc.title}</TableCell>
                <TableCell>{docTypeLabel(doc.doc_type)}</TableCell>
                <TableCell>
                  {doc.application_status ? (
                    <Badge variant={doc.application_status === 'hired' ? 'default' : 'destructive'}>
                      {statusLabel(doc.application_status)}
                    </Badge>
                  ) : '—'}
                </TableCell>
                <TableCell>{new Date(doc.created_at).toLocaleDateString()}</TableCell>
                <TableCell>
                  <a href={doc.file} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">
                    {t('hr.common.download')}
                  </a>
                </TableCell>
                <TableCell>
                  <Button size="sm" variant="outline" onClick={() => startEditDoc(doc)}>
                    {t('hr.common.edit')}
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {/* Edit document dialog */}
      <Dialog open={editDialogOpen} onOpenChange={setEditDialogOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>{t('hr.pages.documents.edit')}</DialogTitle>
          </DialogHeader>
          <div className="grid gap-4">
            <div className="grid gap-4 md:grid-cols-2">
              <label className="grid gap-2 text-sm">
                {t('hr.pages.documents.fields.title')}
                <Input value={editForm.title} onChange={(e) => setEditForm({ ...editForm, title: e.target.value })} />
              </label>
              <label className="grid gap-2 text-sm">
                {t('hr.pages.documents.fields.type')}
                <Select value={editForm.doc_type} onValueChange={(value) => setEditForm({ ...editForm, doc_type: value })}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="contract">{t('hr.pages.documents.docTypes.contract')}</SelectItem>
                    <SelectItem value="order">{t('hr.pages.documents.docTypes.order')}</SelectItem>
                    <SelectItem value="amendment">{t('hr.pages.documents.docTypes.amendment')}</SelectItem>
                    <SelectItem value="certificate">{t('hr.pages.documents.docTypes.certificate')}</SelectItem>
                    <SelectItem value="other">{t('hr.pages.documents.docTypes.other')}</SelectItem>
                  </SelectContent>
                </Select>
              </label>
            </div>

            <label className="grid gap-2 text-sm">
              {t('hr.pages.documents.fields.description')}
              <Textarea value={editForm.description} onChange={(e) => setEditForm({ ...editForm, description: e.target.value })} />
            </label>

            <label className="grid gap-2 text-sm">
              {t('hr.pages.archive.editDialog.replaceFile')}
              <Input type="file" onChange={(e: any) => setEditForm({ ...editForm, file: e.target.files?.[0] || null })} />
            </label>

            {editingDoc?.application && (editingDoc.doc_type === 'contract' || editingDoc.doc_type === 'order') && (
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
                      {editingDoc.doc_type === 'contract' && (
                        <label className="grid gap-1 text-sm">
                          {t('hr.pages.archive.editDialog.fields.workSchedule')}
                          <Input value={pdfFields.work_schedule} onChange={(e) => setPdfFields({ ...pdfFields, work_schedule: e.target.value })} />
                        </label>
                      )}
                    </div>
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => editingDoc && regenerateMutation.mutate({ docId: editingDoc.id, fields: pdfFields })}
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
              <Button variant="outline" onClick={() => setEditDialogOpen(false)}>
                {t('hr.common.cancel')}
              </Button>
              <Button
                onClick={() => editMutation.mutate()}
                disabled={!editForm.title || editMutation.isPending}
              >
                {editMutation.isPending ? t('hr.common.saving') : t('hr.common.save')}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </HRLayout>
  );
};

export default HRArchive;
