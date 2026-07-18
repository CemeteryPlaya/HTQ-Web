import { useState, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { fetchDocuments, uploadDocument, deleteDocument, fetchEmployees } from '@/api/hr';
import type { HRDocument, Employee } from '@/types/hr';
import HRLayout from '@/components/hr/HRLayout';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import {
  FileText, Search, Plus, Trash2, Download, Loader2, AlertCircle, Upload,
} from 'lucide-react';

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */
const formatDate = (d: string | null) => {
  if (!d) return '—';
  return new Date(d).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short', year: 'numeric' });
};

const docTypeBadge = (dt: string) => {
  switch (dt) {
    case 'contract': return 'default' as const;
    case 'amendment': return 'secondary' as const;
    case 'order': return 'outline' as const;
    case 'certificate': return 'default' as const;
    default: return 'outline' as const;
  }
};

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */
const HRDocuments = () => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);

  /* ---- state ---- */
  const [search, setSearch] = useState('');
  const [filterType, setFilterType] = useState<string>('all');
  const [filterEmployee, setFilterEmployee] = useState<string>('all');
  const [dialogOpen, setDialogOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<HRDocument | null>(null);

  /* upload form */
  const [uf, setUf] = useState({ employee: '', title: '', doc_type: 'other', description: '' });
  const [file, setFile] = useState<File | null>(null);
  const [formErrors, setFormErrors] = useState<Record<string, string>>({});

  /* ---- queries ---- */
  const params: Record<string, string> = {};
  if (filterType !== 'all') params.doc_type = filterType;
  if (filterEmployee !== 'all') params.employee = filterEmployee;

  const { data: documents = [], isLoading, isError } = useQuery({
    queryKey: ['hr-documents', filterType, filterEmployee],
    queryFn: () => fetchDocuments(Object.keys(params).length ? params : undefined),
    refetchInterval: 30000,
  });

  const { data: employees = [] } = useQuery({
    queryKey: ['hr-employees'],
    queryFn: () => fetchEmployees(),
  });

  /* ---- mutations ---- */
  const uploadMut = useMutation({
    mutationFn: async () => {
      const fd = new FormData();
      fd.append('employee', uf.employee);
      fd.append('title', uf.title);
      fd.append('doc_type', uf.doc_type);
      fd.append('description', uf.description);
      if (file) fd.append('file', file);
      return uploadDocument(fd);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hr-documents'] });
      closeDialog();
    },
    onError: (err: any) => {
      const data = err?.response?.data;
      if (typeof data === 'object') {
        const mapped: Record<string, string> = {};
        Object.entries(data).forEach(([k, v]) => {
          mapped[k] = Array.isArray(v) ? v.join('. ') : String(v);
        });
        setFormErrors(mapped);
      } else {
        setFormErrors({ _global: err?.message || t('hr.unknownError') });
      }
    },
  });

  const deleteMut = useMutation({
    mutationFn: async (doc: HRDocument) => deleteDocument(doc.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hr-documents'] });
      setDeleteTarget(null);
    },
  });

  /* ---- filtered ---- */
  const filtered = !search.trim()
    ? documents
    : documents.filter((d) => {
        const q = search.toLowerCase();
        return (
          d.title.toLowerCase().includes(q) ||
          d.employee_name.toLowerCase().includes(q) ||
          (d.description || '').toLowerCase().includes(q)
        );
      });

  /* ---- helpers ---- */
  const closeDialog = () => {
    setDialogOpen(false);
    setUf({ employee: '', title: '', doc_type: 'other', description: '' });
    setFile(null);
    setFormErrors({});
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const handleUpload = () => {
    const errs: Record<string, string> = {};
    if (!uf.employee) errs.employee = t('hr.documents.employeeRequired');
    if (!uf.title.trim()) errs.title = t('hr.documents.titleRequired');
    if (!file) errs.file = t('hr.documents.fileRequired');
    setFormErrors(errs);
    if (Object.keys(errs).length > 0) return;
    uploadMut.mutate();
  };

  /* ---------------------------------------------------------------- */
  /*  Render                                                           */
  /* ---------------------------------------------------------------- */
  return (
    <HRLayout>
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-lg bg-primary/10 flex items-center justify-center">
            <FileText className="h-5 w-5 text-primary" />
          </div>
          <div>
            <h1 className="font-display text-2xl font-bold tracking-tight">{t('hr.documents.title')}</h1>
            <p className="text-sm text-muted-foreground">{t('hr.documents.subtitle')}</p>
          </div>
        </div>
        <Button onClick={() => setDialogOpen(true)} className="gap-2">
          <Upload className="h-4 w-4" /> {t('hr.documents.upload')}
        </Button>
      </div>

      {/* Filters */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center gap-3 mb-6">
        <div className="relative flex-1 w-full">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder={t('hr.documents.searchPlaceholder')} className="pl-10" />
        </div>
        <Select value={filterType} onValueChange={setFilterType}>
          <SelectTrigger className="w-44">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t('hr.documents.allTypes')}</SelectItem>
            {['contract', 'amendment', 'order', 'certificate', 'other'].map((dt) => (
              <SelectItem key={dt} value={dt}>{t(`hr.docType.${dt}`)}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={filterEmployee} onValueChange={setFilterEmployee}>
          <SelectTrigger className="w-52">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t('hr.documents.allEmployees')}</SelectItem>
            {employees.map((emp) => (
              <SelectItem key={emp.id} value={String(emp.id)}>{emp.full_name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Loading */}
      {isLoading && (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => <Skeleton key={i} className="h-14 w-full rounded-md" />)}
        </div>
      )}

      {/* Error */}
      {isError && (
        <Card className="border-destructive">
          <CardContent className="flex items-center gap-3 p-6 text-destructive">
            <AlertCircle className="h-5 w-5 shrink-0" />
            <p>{t('hr.loadError')}</p>
          </CardContent>
        </Card>
      )}

      {/* Empty */}
      {!isLoading && !isError && filtered.length === 0 && (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16 text-center text-muted-foreground">
            <FileText className="h-12 w-12 mb-4 opacity-30" />
            <p className="text-lg font-medium">{t('hr.documents.empty')}</p>
            <Button className="mt-4 gap-2" onClick={() => setDialogOpen(true)}>
              <Upload className="h-4 w-4" /> {t('hr.documents.upload')}
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Table */}
      {!isLoading && !isError && filtered.length > 0 && (
        <div className="bg-card rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t('hr.documents.col.title')}</TableHead>
                <TableHead>{t('hr.documents.col.employee')}</TableHead>
                <TableHead>{t('hr.documents.col.type')}</TableHead>
                <TableHead>{t('hr.documents.col.uploadedBy')}</TableHead>
                <TableHead>{t('hr.documents.col.date')}</TableHead>
                <TableHead className="text-right">{t('hr.documents.col.actions')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((doc) => (
                <TableRow key={doc.id}>
                  <TableCell className="font-medium">
                    <div className="flex items-center gap-2">
                      <FileText className="h-4 w-4 text-muted-foreground shrink-0" />
                      {doc.title}
                    </div>
                  </TableCell>
                  <TableCell>{doc.employee_name}</TableCell>
                  <TableCell>
                    <Badge variant={docTypeBadge(doc.doc_type)}>{t(`hr.docType.${doc.doc_type}`)}</Badge>
                  </TableCell>
                  <TableCell>{doc.uploaded_by_name || '—'}</TableCell>
                  <TableCell>{formatDate(doc.created_at)}</TableCell>
                  <TableCell className="text-right">
                    <div className="flex items-center justify-end gap-1">
                      {doc.file && (
                        <Button size="icon" variant="ghost" asChild>
                          <a href={doc.file} target="_blank" rel="noopener noreferrer">
                            <Download className="h-4 w-4" />
                          </a>
                        </Button>
                      )}
                      <Button size="icon" variant="ghost" className="text-destructive" onClick={() => setDeleteTarget(doc)}>
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {/* ============ Upload Dialog ============ */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{t('hr.documents.uploadDialog')}</DialogTitle>
            <DialogDescription>{t('hr.documents.uploadHint')}</DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            {formErrors._global && <p className="text-sm text-destructive">{formErrors._global}</p>}

            <div className="grid gap-2">
              <Label>{t('hr.documents.col.employee')}</Label>
              <Select value={uf.employee} onValueChange={(v) => setUf((f) => ({ ...f, employee: v }))}>
                <SelectTrigger><SelectValue placeholder="—" /></SelectTrigger>
                <SelectContent>
                  {employees.map((emp) => (
                    <SelectItem key={emp.id} value={String(emp.id)}>{emp.full_name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {formErrors.employee && <p className="text-xs text-destructive">{formErrors.employee}</p>}
            </div>

            <div className="grid gap-2">
              <Label>{t('hr.documents.col.title')}</Label>
              <Input value={uf.title} onChange={(e) => setUf((f) => ({ ...f, title: e.target.value }))} />
              {formErrors.title && <p className="text-xs text-destructive">{formErrors.title}</p>}
            </div>

            <div className="grid gap-2">
              <Label>{t('hr.documents.col.type')}</Label>
              <Select value={uf.doc_type} onValueChange={(v) => setUf((f) => ({ ...f, doc_type: v }))}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {['contract', 'amendment', 'order', 'certificate', 'other'].map((dt) => (
                    <SelectItem key={dt} value={dt}>{t(`hr.docType.${dt}`)}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="grid gap-2">
              <Label>{t('hr.documents.description')}</Label>
              <Textarea value={uf.description} onChange={(e) => setUf((f) => ({ ...f, description: e.target.value }))} rows={2} />
            </div>

            <div className="grid gap-2">
              <Label>{t('hr.documents.file')}</Label>
              <Input
                ref={fileInputRef}
                type="file"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
              {formErrors.file && <p className="text-xs text-destructive">{formErrors.file}</p>}
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={closeDialog}>{t('hr.cancel')}</Button>
            <Button onClick={handleUpload} disabled={uploadMut.isPending} className="gap-2">
              {uploadMut.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              {t('hr.documents.upload')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ============ Delete ============ */}
      <AlertDialog open={!!deleteTarget} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('hr.deleteConfirmTitle')}</AlertDialogTitle>
            <AlertDialogDescription>{t('hr.deleteConfirmText', { name: deleteTarget?.title })}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('hr.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => deleteTarget && deleteMut.mutate(deleteTarget)}
            >
              {t('hr.delete')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </HRLayout>
  );
};

export default HRDocuments;
