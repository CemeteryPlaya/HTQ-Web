import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  fetchVacancies, createVacancy, updateVacancy, deleteVacancy,
  fetchApplications, createApplication, updateApplication, deleteApplication,
  fetchDepartments,
} from '@/api/hr';
import type { Vacancy, Application, Department } from '@/types/hr';
import HRLayout from '@/components/hr/HRLayout';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
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
  Briefcase, Search, Plus, Pencil, Trash2, Loader2, AlertCircle,
  Users, CheckCircle, PauseCircle, FileText,
} from 'lucide-react';

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */
const formatDate = (d: string | null) => {
  if (!d) return '—';
  return new Date(d).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short', year: 'numeric' });
};

const vacancyStatusVariant = (s: string) => {
  switch (s) {
    case 'open': return 'default' as const;
    case 'closed': return 'secondary' as const;
    case 'on_hold': return 'outline' as const;
    default: return 'outline' as const;
  }
};

const appStatusVariant = (s: string) => {
  switch (s) {
    case 'new': return 'default' as const;
    case 'reviewed': return 'secondary' as const;
    case 'interview': return 'outline' as const;
    case 'offered': return 'default' as const;
    case 'hired': return 'default' as const;
    case 'rejected': return 'destructive' as const;
    default: return 'outline' as const;
  }
};

interface VacancyForm {
  title: string;
  department: string;
  description: string;
  requirements: string;
  salary_min: string;
  salary_max: string;
  status: string;
}

const emptyVacancyForm: VacancyForm = {
  title: '', department: '', description: '', requirements: '',
  salary_min: '', salary_max: '', status: 'open',
};

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */
const HRRecruitment = () => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  /* ---- state ---- */
  const [search, setSearch] = useState('');
  const [tab, setTab] = useState('vacancies');
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<Vacancy | null>(null);
  const [form, setForm] = useState<VacancyForm>({ ...emptyVacancyForm });
  const [formErrors, setFormErrors] = useState<Record<string, string>>({});
  const [deleteTarget, setDeleteTarget] = useState<Vacancy | null>(null);
  const [selectedVacancy, setSelectedVacancy] = useState<number | null>(null);
  const [appStatusUpdate, setAppStatusUpdate] = useState<{id: number; status: string} | null>(null);

  /* ---- queries ---- */
  const { data: vacancies = [], isLoading: vacLoading, isError: vacError } = useQuery({
    queryKey: ['hr-vacancies'],
    queryFn: fetchVacancies,
    refetchInterval: 30000,
  });

  const appParams = selectedVacancy ? { vacancy: String(selectedVacancy) } : undefined;
  const { data: applications = [], isLoading: appLoading } = useQuery({
    queryKey: ['hr-applications', selectedVacancy],
    queryFn: () => fetchApplications(appParams),
    refetchInterval: 30000,
  });

  const { data: departments = [] } = useQuery({
    queryKey: ['hr-departments'],
    queryFn: fetchDepartments,
  });

  /* ---- mutations ---- */
  const saveVacancy = useMutation({
    mutationFn: async () => {
      const payload: any = {
        title: form.title,
        department: form.department ? Number(form.department) : null,
        description: form.description,
        requirements: form.requirements,
        salary_min: form.salary_min || null,
        salary_max: form.salary_max || null,
        status: form.status,
      };
      if (editing) return updateVacancy(editing.id, payload);
      return createVacancy(payload);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hr-vacancies'] });
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

  const deleteVacancyMut = useMutation({
    mutationFn: async (v: Vacancy) => deleteVacancy(v.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hr-vacancies'] });
      setDeleteTarget(null);
    },
  });

  const updateAppStatus = useMutation({
    mutationFn: async ({ id, status }: { id: number; status: string }) => updateApplication(id, { status: status as any }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hr-applications'] });
      setAppStatusUpdate(null);
    },
  });

  /* ---- filtered vacancies ---- */
  const filteredVacancies = useMemo(() => {
    if (!search.trim()) return vacancies;
    const q = search.toLowerCase();
    return vacancies.filter(
      (v) => v.title.toLowerCase().includes(q) || (v.department_name || '').toLowerCase().includes(q),
    );
  }, [vacancies, search]);

  /* ---- stats ---- */
  const openCount = vacancies.filter((v) => v.status === 'open').length;
  const totalApps = vacancies.reduce((acc, v) => acc + v.applications_count, 0);

  /* ---- dialog helpers ---- */
  const openCreate = () => {
    setEditing(null);
    setForm({ ...emptyVacancyForm });
    setFormErrors({});
    setDialogOpen(true);
  };

  const openEdit = (v: Vacancy) => {
    setEditing(v);
    setForm({
      title: v.title,
      department: v.department ? String(v.department) : '',
      description: v.description,
      requirements: v.requirements,
      salary_min: v.salary_min || '',
      salary_max: v.salary_max || '',
      status: v.status,
    });
    setFormErrors({});
    setDialogOpen(true);
  };

  const closeDialog = () => {
    setDialogOpen(false);
    setEditing(null);
    setForm({ ...emptyVacancyForm });
    setFormErrors({});
  };

  const handleSave = () => {
    const errs: Record<string, string> = {};
    if (!form.title.trim()) errs.title = t('hr.recruitment.titleRequired');
    setFormErrors(errs);
    if (Object.keys(errs).length > 0) return;
    saveVacancy.mutate();
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
            <Briefcase className="h-5 w-5 text-primary" />
          </div>
          <div>
            <h1 className="font-display text-2xl font-bold tracking-tight">{t('hr.recruitment.title')}</h1>
            <p className="text-sm text-muted-foreground">{t('hr.recruitment.subtitle')}</p>
          </div>
        </div>
        <Button onClick={openCreate} className="gap-2">
          <Plus className="h-4 w-4" /> {t('hr.recruitment.addVacancy')}
        </Button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
        <Card>
          <CardContent className="flex items-center gap-4 p-4">
            <div className="h-10 w-10 rounded-full bg-blue-100 dark:bg-blue-900/30 flex items-center justify-center">
              <FileText className="h-5 w-5 text-blue-600 dark:text-blue-400" />
            </div>
            <div>
              <p className="text-2xl font-bold">{vacancies.length}</p>
              <p className="text-xs text-muted-foreground">{t('hr.recruitment.totalVacancies')}</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-center gap-4 p-4">
            <div className="h-10 w-10 rounded-full bg-green-100 dark:bg-green-900/30 flex items-center justify-center">
              <CheckCircle className="h-5 w-5 text-green-600 dark:text-green-400" />
            </div>
            <div>
              <p className="text-2xl font-bold">{openCount}</p>
              <p className="text-xs text-muted-foreground">{t('hr.recruitment.openVacancies')}</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-center gap-4 p-4">
            <div className="h-10 w-10 rounded-full bg-purple-100 dark:bg-purple-900/30 flex items-center justify-center">
              <Users className="h-5 w-5 text-purple-600 dark:text-purple-400" />
            </div>
            <div>
              <p className="text-2xl font-bold">{totalApps}</p>
              <p className="text-xs text-muted-foreground">{t('hr.recruitment.totalApplications')}</p>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Tabs */}
      <Tabs value={tab} onValueChange={setTab} className="space-y-4">
        <TabsList>
          <TabsTrigger value="vacancies">{t('hr.recruitment.vacanciesTab')}</TabsTrigger>
          <TabsTrigger value="applications">{t('hr.recruitment.applicationsTab')}</TabsTrigger>
        </TabsList>

        {/* ======== Vacancies tab ======== */}
        <TabsContent value="vacancies" className="space-y-4">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder={t('hr.recruitment.searchPlaceholder')} className="pl-10" />
          </div>

          {vacLoading && (
            <div className="space-y-3">
              {[1, 2, 3].map((i) => <Skeleton key={i} className="h-14 w-full rounded-md" />)}
            </div>
          )}

          {vacError && (
            <Card className="border-destructive">
              <CardContent className="flex items-center gap-3 p-6 text-destructive">
                <AlertCircle className="h-5 w-5 shrink-0" />
                <p>{t('hr.loadError')}</p>
              </CardContent>
            </Card>
          )}

          {!vacLoading && !vacError && filteredVacancies.length === 0 && (
            <Card>
              <CardContent className="flex flex-col items-center justify-center py-16 text-center text-muted-foreground">
                <Briefcase className="h-12 w-12 mb-4 opacity-30" />
                <p className="text-lg font-medium">{t('hr.recruitment.emptyVacancies')}</p>
                <Button className="mt-4 gap-2" onClick={openCreate}>
                  <Plus className="h-4 w-4" /> {t('hr.recruitment.addVacancy')}
                </Button>
              </CardContent>
            </Card>
          )}

          {!vacLoading && !vacError && filteredVacancies.length > 0 && (
            <div className="grid gap-3">
              {filteredVacancies.map((v) => (
                <Card key={v.id} className="hover:shadow-md transition-all">
                  <CardContent className="flex items-center justify-between gap-4 p-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap mb-1">
                        <h3 className="font-semibold truncate">{v.title}</h3>
                        <Badge variant={vacancyStatusVariant(v.status)}>{t(`hr.vacancyStatus.${v.status}`)}</Badge>
                        {v.department_name && <Badge variant="outline">{v.department_name}</Badge>}
                      </div>
                      <div className="flex items-center gap-4 text-xs text-muted-foreground">
                        <span>{formatDate(v.created_at)}</span>
                        <span className="flex items-center gap-1">
                          <Users className="h-3 w-3" /> {v.applications_count} {t('hr.recruitment.apps')}
                        </span>
                        {(v.salary_min || v.salary_max) && (
                          <span>
                            {v.salary_min && `${Number(v.salary_min).toLocaleString()}`}
                            {v.salary_min && v.salary_max && ' – '}
                            {v.salary_max && `${Number(v.salary_max).toLocaleString()}`} ₸
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-1 shrink-0">
                      <Button size="icon" variant="ghost" onClick={() => { setSelectedVacancy(v.id); setTab('applications'); }}>
                        <Users className="h-4 w-4" />
                      </Button>
                      <Button size="icon" variant="ghost" onClick={() => openEdit(v)}>
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button size="icon" variant="ghost" className="text-destructive" onClick={() => setDeleteTarget(v)}>
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </TabsContent>

        {/* ======== Applications tab ======== */}
        <TabsContent value="applications" className="space-y-4">
          <div className="flex items-center gap-4 mb-2">
            <Select
              value={selectedVacancy ? String(selectedVacancy) : 'all'}
              onValueChange={(v) => setSelectedVacancy(v === 'all' ? null : Number(v))}
            >
              <SelectTrigger className="w-72">
                <SelectValue placeholder={t('hr.recruitment.allVacancies')} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t('hr.recruitment.allVacancies')}</SelectItem>
                {vacancies.map((v) => (
                  <SelectItem key={v.id} value={String(v.id)}>{v.title}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {appLoading && (
            <div className="space-y-3">
              {[1, 2, 3].map((i) => <Skeleton key={i} className="h-14 w-full rounded-md" />)}
            </div>
          )}

          {!appLoading && applications.length === 0 && (
            <Card>
              <CardContent className="flex flex-col items-center justify-center py-16 text-center text-muted-foreground">
                <Users className="h-12 w-12 mb-4 opacity-30" />
                <p className="text-lg font-medium">{t('hr.recruitment.emptyApplications')}</p>
              </CardContent>
            </Card>
          )}

          {!appLoading && applications.length > 0 && (
            <div className="bg-card rounded-lg border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t('hr.recruitment.col.candidate')}</TableHead>
                    <TableHead>{t('hr.recruitment.col.vacancy')}</TableHead>
                    <TableHead>{t('hr.recruitment.col.email')}</TableHead>
                    <TableHead>{t('hr.recruitment.col.date')}</TableHead>
                    <TableHead>{t('hr.recruitment.col.status')}</TableHead>
                    <TableHead>{t('hr.recruitment.col.actions')}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {applications.map((app) => (
                    <TableRow key={app.id}>
                      <TableCell className="font-medium">{app.first_name} {app.last_name}</TableCell>
                      <TableCell>{app.vacancy_title}</TableCell>
                      <TableCell>{app.email}</TableCell>
                      <TableCell>{formatDate(app.created_at)}</TableCell>
                      <TableCell>
                        <Badge variant={appStatusVariant(app.status)}>{t(`hr.appStatus.${app.status}`)}</Badge>
                      </TableCell>
                      <TableCell>
                        <Select
                          value={app.status}
                          onValueChange={(v) => updateAppStatus.mutate({ id: app.id, status: v })}
                        >
                          <SelectTrigger className="w-36 h-8 text-xs">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {['new', 'reviewed', 'interview', 'offered', 'rejected', 'hired'].map((s) => (
                              <SelectItem key={s} value={s}>{t(`hr.appStatus.${s}`)}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </TabsContent>
      </Tabs>

      {/* ============ Vacancy Dialog ============ */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-lg max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{editing ? t('hr.recruitment.editVacancy') : t('hr.recruitment.addVacancy')}</DialogTitle>
            <DialogDescription>{editing ? t('hr.recruitment.editHint') : t('hr.recruitment.addHint')}</DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            {formErrors._global && <p className="text-sm text-destructive">{formErrors._global}</p>}

            <div className="grid gap-2">
              <Label>{t('hr.recruitment.vacancyTitle')}</Label>
              <Input value={form.title} onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))} />
              {formErrors.title && <p className="text-xs text-destructive">{formErrors.title}</p>}
            </div>

            <div className="grid gap-2">
              <Label>{t('hr.employees.col.department')}</Label>
              <Select value={form.department} onValueChange={(v) => setForm((f) => ({ ...f, department: v }))}>
                <SelectTrigger><SelectValue placeholder="—" /></SelectTrigger>
                <SelectContent>
                  {departments.map((d) => (
                    <SelectItem key={d.id} value={String(d.id)}>{d.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="grid gap-2">
              <Label>{t('hr.recruitment.description')}</Label>
              <Textarea value={form.description} onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))} rows={3} />
            </div>

            <div className="grid gap-2">
              <Label>{t('hr.recruitment.requirements')}</Label>
              <Textarea value={form.requirements} onChange={(e) => setForm((f) => ({ ...f, requirements: e.target.value }))} rows={3} />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="grid gap-2">
                <Label>{t('hr.recruitment.salaryMin')}</Label>
                <Input type="number" value={form.salary_min} onChange={(e) => setForm((f) => ({ ...f, salary_min: e.target.value }))} />
              </div>
              <div className="grid gap-2">
                <Label>{t('hr.recruitment.salaryMax')}</Label>
                <Input type="number" value={form.salary_max} onChange={(e) => setForm((f) => ({ ...f, salary_max: e.target.value }))} />
              </div>
            </div>

            <div className="grid gap-2">
              <Label>{t('hr.employees.col.status')}</Label>
              <Select value={form.status} onValueChange={(v) => setForm((f) => ({ ...f, status: v }))}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="open">{t('hr.vacancyStatus.open')}</SelectItem>
                  <SelectItem value="closed">{t('hr.vacancyStatus.closed')}</SelectItem>
                  <SelectItem value="on_hold">{t('hr.vacancyStatus.on_hold')}</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={closeDialog}>{t('hr.cancel')}</Button>
            <Button onClick={handleSave} disabled={saveVacancy.isPending} className="gap-2">
              {saveVacancy.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              {t('hr.save')}
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
              onClick={() => deleteTarget && deleteVacancyMut.mutate(deleteTarget)}
            >
              {t('hr.delete')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </HRLayout>
  );
};

export default HRRecruitment;
