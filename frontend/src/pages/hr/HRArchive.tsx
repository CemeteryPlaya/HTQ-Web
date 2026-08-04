import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import api from '@/api/client';
import HRLayout from '@/components/hr/HRLayout';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { HRArchiveResponse, HRArchiveApplication, HRArchiveDocument } from '@/types/hr';
import { reportApiError } from '@/lib/apiError';

type DocSortKey = 'employee' | 'title' | 'type' | 'date';

/**
 * Имена сотрудников и названия вакансий бэкенд в архиве не отдаёт — только
 * id (`recruitment_service.archive()`), поэтому разворачиваем их по тем же
 * справочникам, что и остальные HR-страницы.
 */
interface EmployeeOption {
  id: number;
  first_name: string;
  last_name: string;
  middle_name?: string | null;
  email?: string | null;
}

interface VacancyOption {
  id: number;
  title: string;
}

const employeeName = (emp?: EmployeeOption): string => {
  if (!emp) return '';
  const full = [emp.last_name, emp.first_name, emp.middle_name].filter(Boolean).join(' ').trim();
  return full || emp.email || `#${emp.id}`;
};

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

  const { data: employees } = useQuery({
    queryKey: ['hr-employees'],
    queryFn: async () => {
      const res = await api.get<EmployeeOption[]>('hr/v1/employees/');
      return res.data;
    },
  });

  const { data: vacancies } = useQuery({
    queryKey: ['hr-vacancies'],
    queryFn: async () => {
      const res = await api.get<VacancyOption[]>('hr/v1/vacancies/');
      return res.data;
    },
  });

  const applications = data?.applications ?? [];
  const documents = data?.documents ?? [];

  const employeeById = useMemo(() => {
    const map = new Map<number, EmployeeOption>();
    (employees || []).forEach((emp) => map.set(emp.id, emp));
    return map;
  }, [employees]);

  const vacancyById = useMemo(() => {
    const map = new Map<number, VacancyOption>();
    (vacancies || []).forEach((vacancy) => map.set(vacancy.id, vacancy));
    return map;
  }, [vacancies]);

  const [docFilters, setDocFilters] = useState({
    employee: '',
    title: '',
    type: 'all',
    dateFrom: '',
    dateTo: '',
  });

  const [docSort, setDocSort] = useState<{ key: DocSortKey; direction: 'asc' | 'desc' }>({
    key: 'date',
    direction: 'desc',
  });

  // ── Правка карточки документа (PATCH /documents/{id}/) ──
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [editingDoc, setEditingDoc] = useState<HRArchiveDocument | null>(null);
  const [editForm, setEditForm] = useState({ title: '', doc_type: 'other', description: '' });
  const [descriptionLoading, setDescriptionLoading] = useState(false);

  const startEditDoc = (doc: HRArchiveDocument) => {
    setEditingDoc(doc);
    setEditForm({ title: doc.title || '', doc_type: doc.doc_type || 'other', description: '' });
    setEditDialogOpen(true);

    // Описание живёт в metadata и в ответе архива не приходит — дочитываем
    // карточку целиком, иначе сохранение затёрло бы его пустой строкой.
    setDescriptionLoading(true);
    api
      .get(`hr/v1/documents/${doc.id}/`)
      .then((res) => {
        setEditForm((prev) => ({ ...prev, description: res.data?.metadata?.description || '' }));
      })
      .catch(() => undefined)
      .finally(() => setDescriptionLoading(false));
  };

  const editMutation = useMutation({
    mutationFn: async () => {
      if (!editingDoc) return null;
      // Только карточка: файл PATCH'ем не заменить — перезалив делается
      // новой загрузкой на странице «Документы».
      const res = await api.patch(`hr/v1/documents/${editingDoc.id}/`, {
        title: editForm.title,
        doc_type: editForm.doc_type,
        description: editForm.description,
      });
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hr-archive'] });
      queryClient.invalidateQueries({ queryKey: ['hr-documents'] });
      setEditDialogOpen(false);
      setEditingDoc(null);
    },
    onError: (err) => reportApiError(err, t('hr.common.unknownError')),
  });

  const statusLabel = (status: HRArchiveApplication['status']) => {
    if (status === 'hired') return t('hr.pages.archive.status.hired');
    if (status === 'rejected') return t('hr.pages.archive.status.rejected');
    return status;
  };

  const statusVariant = (status: HRArchiveApplication['status']) =>
    (status === 'hired' ? 'default' : 'destructive') as const;

  const docTypeLabel = (docType: string) => {
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
    const docEmployee = employeeName(employeeById.get(doc.employee_id));
    if (docFilters.employee && !matches(docEmployee, docFilters.employee)) return false;
    if (docFilters.title && !matches(doc.title, docFilters.title)) return false;
    if (docFilters.type !== 'all' && doc.doc_type !== docFilters.type) return false;
    if ((docFilters.dateFrom || docFilters.dateTo) && !inDateRange(doc.created_at, docFilters.dateFrom, docFilters.dateTo)) {
      return false;
    }
    return true;
  });

  const sortedDocuments = [...filteredDocuments].sort((a, b) => {
    if (docSort.key === 'date') {
      const leftDate = new Date(a.created_at).getTime();
      const rightDate = new Date(b.created_at).getTime();
      return docSort.direction === 'asc' ? leftDate - rightDate : rightDate - leftDate;
    }

    let left = '';
    let right = '';
    if (docSort.key === 'employee') {
      left = employeeName(employeeById.get(a.employee_id));
      right = employeeName(employeeById.get(b.employee_id));
    } else if (docSort.key === 'title') {
      left = a.title || '';
      right = b.title || '';
    } else if (docSort.key === 'type') {
      left = a.doc_type || '';
      right = b.doc_type || '';
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
    setDocFilters({ employee: '', title: '', type: 'all', dateFrom: '', dateTo: '' });
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
                <TableCell className="font-medium">{item.candidate_name}</TableCell>
                <TableCell>{item.candidate_email || '—'}</TableCell>
                <TableCell>{vacancyById.get(item.vacancy_id)?.title || `#${item.vacancy_id}`}</TableCell>
                <TableCell><Badge variant={statusVariant(item.status)}>{statusLabel(item.status)}</Badge></TableCell>
                <TableCell>{item.created_at ? new Date(item.created_at).toLocaleDateString() : '—'}</TableCell>
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
              placeholder={t('hr.pages.archive.documents.title')}
              value={docFilters.title}
              onChange={(e) => setDocFilters((prev) => ({ ...prev, title: e.target.value }))}
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
            <div className="grid grid-cols-2 gap-2">
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
                <button type="button" onClick={() => toggleSort('date')} className="flex items-center gap-1">
                  {t('hr.pages.archive.documents.date')}{sortIndicator('date')}
                </button>
              </TableHead>
              <TableHead>{t('hr.common.actions')}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {sortedDocuments.length === 0 && (
              <TableRow>
                <TableCell colSpan={5} className="text-center text-muted-foreground py-8">
                  {t('hr.pages.archive.emptyDocuments')}
                </TableCell>
              </TableRow>
            )}
            {sortedDocuments.map((doc) => (
              <TableRow key={doc.id}>
                <TableCell className="font-medium">
                  {employeeName(employeeById.get(doc.employee_id)) || `#${doc.employee_id}`}
                </TableCell>
                <TableCell>{doc.title}</TableCell>
                <TableCell>{docTypeLabel(doc.doc_type)}</TableCell>
                <TableCell>{doc.created_at ? new Date(doc.created_at).toLocaleDateString() : '—'}</TableCell>
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

      {/* Правка карточки документа */}
      <Dialog open={editDialogOpen} onOpenChange={setEditDialogOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>{t('hr.pages.documents.edit')}</DialogTitle>
            <DialogDescription>{t('hr.pages.archive.editDialog.cardOnlyHint')}</DialogDescription>
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
              <Textarea
                value={editForm.description}
                disabled={descriptionLoading}
                onChange={(e) => setEditForm({ ...editForm, description: e.target.value })}
              />
            </label>

            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setEditDialogOpen(false)}>
                {t('hr.common.cancel')}
              </Button>
              <Button
                onClick={() => editMutation.mutate()}
                disabled={!editForm.title || descriptionLoading || editMutation.isPending}
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
