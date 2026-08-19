import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import api from '@/api/client';
import HRLayout from '@/components/hr/HRLayout';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { useHRLevel } from '@/hooks/useHRLevel';
import { cn } from '@/lib/utils';
import { ChevronDown, ChevronRight, Plus, Pencil, Trash2, Building2, Briefcase, Search } from 'lucide-react';

/* ------------------------------------------------------------------ */
/*  Types                                                             */
/* ------------------------------------------------------------------ */

interface Position {
  id: number;
  title: string;
  department_id: number;
  grade?: number;
  weight?: number;
  level?: number;
}

interface Department {
  id: number;
  name: string;
  description: string;
  index: number | null;
  positions: Position[];
  created_at: string;
}

/* ------------------------------------------------------------------ */
/*  Component                                                         */
/* ------------------------------------------------------------------ */

const HRDepartments = () => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { isSenior } = useHRLevel();

  /* ---- Data ---- */
  const { data: departments, isLoading, error } = useQuery({
    queryKey: ['hr-departments'],
    queryFn: async () => {
      const res = await api.get<Department[]>('hr/v1/departments/');
      return res.data;
    },
  });

  /* ---- UI State ---- */
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [search, setSearch] = useState('');

  // Department dialog
  const [deptDialogOpen, setDeptDialogOpen] = useState(false);
  const [editingDept, setEditingDept] = useState<Department | null>(null);
  const [deptForm, setDeptForm] = useState({ name: '', description: '' });

  // Position dialog
  const [posDialogOpen, setPosDialogOpen] = useState(false);
  const [editingPos, setEditingPos] = useState<Position | null>(null);
  const [posForm, setPosForm] = useState({ title: '', department_id: 0 });

  /* ---- Mutations ---- */
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['hr-departments'] });

  const saveDeptMutation = useMutation({
    mutationFn: async () => {
      if (editingDept) {
        return (await api.put(`hr/v1/departments/${editingDept.id}/`, deptForm)).data;
      }
      return (await api.post('hr/v1/departments/', deptForm)).data;
    },
    onSuccess: () => { invalidate(); closeDeptDialog(); },
  });

  const deleteDeptMutation = useMutation({
    mutationFn: async ({ id, cascade }: { id: number; cascade?: boolean }) => {
      const url = `hr/v1/departments/${id}/${cascade ? '?cascade=true' : ''}`;
      await api.delete(url);
    },
    onSuccess: invalidate,
  });

  /**
   * Backend returns 409 with structured `blockers` when the dept is not
   * empty. Show a confirm summarising what would be cascaded, then retry
   * with `?cascade=true` so the server hard-deletes the whole subtree.
   */
  const handleDeleteDept = async (id: number, name: string) => {
    if (!confirm(t('hr.pages.departments.deleteConfirm') + `\n\n«${name}»`)) return;
    try {
      await deleteDeptMutation.mutateAsync({ id });
      return;
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      const blockers =
        detail && typeof detail === 'object' && detail.blockers ? detail.blockers : null;
      if (err?.response?.status === 409 && blockers) {
        const parts: string[] = [];
        if (blockers.sub_departments) parts.push(`${blockers.sub_departments} подразделение(й)`);
        if (blockers.positions) parts.push(`${blockers.positions} должность(ей)`);
        if (blockers.employees) parts.push(`${blockers.employees} сотрудник(ов)`);
        const ok = confirm(
          `Подразделение «${name}» содержит ${parts.join(', ')}.\n` +
            `Удалить вместе со всем содержимым? Это действие необратимо.`,
        );
        if (!ok) return;
        await deleteDeptMutation.mutateAsync({ id, cascade: true });
        return;
      }
      const msg = typeof detail === 'string' ? detail : 'Не удалось удалить';
      alert(msg);
    }
  };

  const savePosMutation = useMutation({
    mutationFn: async () => {
      const payload = { title: posForm.title, department_id: posForm.department_id };
      if (editingPos) {
        return (await api.put(`hr/v1/positions/${editingPos.id}/`, payload)).data;
      }
      return (await api.post('hr/v1/positions/', payload)).data;
    },
    onSuccess: () => { invalidate(); closePosDialog(); },
  });

  const deletePosMutation = useMutation({
    mutationFn: async (id: number) => { await api.delete(`hr/v1/positions/${id}/`); },
    onSuccess: invalidate,
  });

  /* ---- Helpers ---- */
  const toggle = (id: number) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const closeDeptDialog = () => { setDeptDialogOpen(false); setEditingDept(null); setDeptForm({ name: '', description: '' }); };
  const closePosDialog = () => { setPosDialogOpen(false); setEditingPos(null); setPosForm({ title: '', department_id: 0 }); };

  const startCreateDept = () => { setEditingDept(null); setDeptForm({ name: '', description: '' }); setDeptDialogOpen(true); };
  const startEditDept = (dept: Department) => { setEditingDept(dept); setDeptForm({ name: dept.name, description: dept.description || '' }); setDeptDialogOpen(true); };

  const startCreatePos = (deptId: number) => { setEditingPos(null); setPosForm({ title: '', department_id: deptId }); setPosDialogOpen(true); };
  const startEditPos = (pos: Position) => { setEditingPos(pos); setPosForm({ title: pos.title, department_id: pos.department_id || 0 }); setPosDialogOpen(true); };

  /* ---- Filtering ---- */
  const filtered = (departments ?? []).filter((dept) =>
    dept.name.toLowerCase().includes(search.trim().toLowerCase()) ||
    dept.positions?.some((p) => p.title.toLowerCase().includes(search.trim().toLowerCase()))
  );

  /* ---- Early returns ---- */
  if (isLoading) {
    return (
      <HRLayout title={t('hr.pages.structure.title')} subtitle={t('hr.pages.structure.subtitle')}>
        <div className="rounded-2xl border bg-card/70 p-8 text-center">{t('hr.common.loading')}</div>
      </HRLayout>
    );
  }
  if (error) {
    return (
      <HRLayout title={t('hr.pages.structure.title')} subtitle={t('hr.pages.structure.subtitle')}>
        <div className="rounded-2xl border bg-card/70 p-8 text-center text-red-500">
          {t('hr.pages.departments.error')}
        </div>
      </HRLayout>
    );
  }

  return (
    <HRLayout title={t('hr.pages.structure.title')} subtitle={t('hr.pages.structure.subtitle')}>
      {/* ---- Header Action Control Bar ---- */}
      <div className="rounded-3xl border bg-card p-4 shadow-2xs">
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
          <div className="flex items-center gap-3 flex-1 w-full sm:w-auto">
            <div className="relative flex-1 max-w-sm">
              <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={t('hr.pages.departments.searchPlaceholder', 'Поиск по подразделениям и должностям...')}
                className="pl-9 h-9 text-xs bg-muted/30 rounded-xl"
              />
            </div>
            <span className="text-xs font-semibold text-muted-foreground whitespace-nowrap">
              {t('hr.common.total')}: {filtered.length}
            </span>
          </div>

          <Button onClick={startCreateDept} className="gap-2 rounded-xl bg-primary text-primary-foreground hover:bg-primary/90 font-semibold shadow-2xs">
            <Plus className="h-4 w-4" />
            {t('hr.pages.departments.create', 'Создать подразделение')}
          </Button>
        </div>
      </div>

      {/* ---- Tree Cards ---- */}
      <div className="space-y-3 mt-4">
        {filtered.map((dept) => {
          const isOpen = expanded.has(dept.id);
          const posCount = dept.positions?.length || 0;

          return (
            <div
              key={dept.id}
              className={cn(
                'rounded-3xl border bg-card shadow-2xs transition-all overflow-hidden',
                // Раскрытое состояние видно по самой карточке, а не только по
                // шеврону в 16px: при десятке отделов на экране понять с одного
                // взгляда, какие открыты, иначе невозможно.
                isOpen ? 'border-primary/40 shadow-xs ring-1 ring-primary/15' : 'hover:shadow-xs',
              )}
            >
              {/* Department row — переключатель целиком, а не только шеврон */}
              <div
                role="button"
                tabIndex={0}
                aria-expanded={isOpen}
                aria-controls={`dept-${dept.id}-positions`}
                // Имя задаём явно: иначе скринридер зачитал бы всё содержимое
                // строки вместе с вложенными кнопками действий.
                aria-label={t('hr.pages.structure.togglePositions', 'Должности отдела {{name}}', { name: dept.name })}
                onClick={() => toggle(dept.id)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    toggle(dept.id);
                  }
                }}
                className={cn(
                  'flex cursor-pointer items-center gap-3 px-6 py-4 transition-colors',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40',
                  isOpen ? 'bg-muted/40' : 'hover:bg-muted/20',
                )}
              >
                <span
                  aria-hidden
                  className="rounded-lg p-1 text-muted-foreground transition-colors"
                >
                  {isOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                </span>

                <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary/10 text-primary shrink-0">
                  <Building2 className="h-4.5 w-4.5" />
                </div>

                <div className="flex-1 min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    {dept.index && (
                      <span className="text-xs font-mono font-bold text-muted-foreground bg-muted/60 px-2 py-0.5 rounded-md">
                        № {dept.index}
                      </span>
                    )}
                    <span className="font-bold text-base truncate text-foreground">{dept.name}</span>
                    {/* При нуле бейдж говорит об этом прямо: тогда пустой
                        результат раскрытия перестаёт быть неожиданностью. */}
                    <span
                      className={cn(
                        'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold',
                        posCount > 0
                          ? 'bg-muted/80 text-muted-foreground'
                          : 'bg-muted/40 text-muted-foreground/70',
                      )}
                    >
                      {posCount > 0 ? `${posCount} должностей` : 'нет должностей'}
                    </span>
                  </div>
                  {dept.description && (
                    <p className="text-xs text-muted-foreground mt-0.5 truncate">{dept.description}</p>
                  )}
                </div>

                {/* Строка целиком — переключатель, поэтому клик по кнопкам
                    действий не должен заодно сворачивать карточку. */}
                <div className="flex items-center gap-1.5 shrink-0" onClick={(e) => e.stopPropagation()}>
                  <Button size="sm" variant="outline" className="gap-1.5 text-xs rounded-xl h-8" onClick={() => startCreatePos(dept.id)} title={t('hr.pages.structure.addPosition')}>
                    <Plus className="h-3.5 w-3.5" />
                    <span>Должность</span>
                  </Button>
                  <Button size="sm" variant="ghost" className="h-8 w-8 p-0 rounded-xl" onClick={() => startEditDept(dept)} title="Редактировать">
                    <Pencil className="h-3.5 w-3.5" />
                  </Button>
                  {isSenior && (
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-8 w-8 p-0 rounded-xl text-destructive hover:text-destructive hover:bg-destructive/10"
                      onClick={() => handleDeleteDept(dept.id, dept.name)}
                      title="Удалить"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  )}
                </div>
              </div>

              {/* Nested positions */}
              {isOpen && dept.positions && dept.positions.length > 0 && (
                <div id={`dept-${dept.id}-positions`} className="border-t bg-muted/30">
                  {dept.positions.map((pos) => (
                    <div key={pos.id} className="flex items-center gap-3 px-5 py-3 pl-14 border-b last:border-b-0">
                      <Briefcase className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                      <span className="flex-1 text-sm">{pos.title}</span>
                      <div className="flex items-center gap-1 shrink-0">
                        <Button size="sm" variant="ghost" onClick={() => startEditPos(pos)}>
                          <Pencil className="h-3 w-3" />
                        </Button>
                        {isSenior && (
                          <Button
                            size="sm"
                            variant="ghost"
                            className="text-destructive hover:text-destructive"
                            onClick={() => {
                              if (confirm(t('hr.pages.positions.deleteConfirm'))) {
                                deletePosMutation.mutate(pos.id);
                              }
                            }}
                          >
                            <Trash2 className="h-3 w-3" />
                          </Button>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Empty state for open dept */}
              {isOpen && (!dept.positions || dept.positions.length === 0) && (
                <div id={`dept-${dept.id}-positions`} className="border-t bg-muted/30 px-5 py-4 pl-14">
                  {/* Рамка и иконка: пустой ответ должен читаться как ответ,
                      а не как «ничего не произошло». */}
                  <div className="flex flex-wrap items-center gap-2 rounded-lg border border-dashed px-3 py-2 text-sm text-muted-foreground">
                    <Briefcase className="h-4 w-4 shrink-0" />
                    {t('hr.pages.structure.noPositions')}
                    <Button size="sm" variant="link" className="p-0 h-auto" onClick={() => startCreatePos(dept.id)}>
                      {t('hr.pages.structure.addPosition')}
                    </Button>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* ---- Department Dialog ---- */}
      <Dialog open={deptDialogOpen} onOpenChange={setDeptDialogOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{editingDept ? t('hr.pages.departments.edit') : t('hr.pages.departments.new')}</DialogTitle>
          </DialogHeader>
          <div className="grid gap-4">
            <label className="grid gap-2 text-sm">
              {t('hr.pages.departments.fields.name')}
              <Input value={deptForm.name} onChange={(e) => setDeptForm({ ...deptForm, name: e.target.value })} />
            </label>
            <label className="grid gap-2 text-sm">
              {t('hr.pages.departments.fields.description')}
              <Textarea value={deptForm.description} onChange={(e) => setDeptForm({ ...deptForm, description: e.target.value })} />
            </label>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={closeDeptDialog}>{t('hr.common.cancel')}</Button>
              <Button onClick={() => saveDeptMutation.mutate()} disabled={!deptForm.name || saveDeptMutation.isPending}>
                {saveDeptMutation.isPending ? t('hr.common.saving') : t('hr.common.save')}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* ---- Position Dialog ---- */}
      <Dialog open={posDialogOpen} onOpenChange={setPosDialogOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{editingPos ? t('hr.pages.positions.edit') : t('hr.pages.positions.new')}</DialogTitle>
          </DialogHeader>
          <div className="grid gap-4">
            <label className="grid gap-2 text-sm">
              {t('hr.pages.positions.fields.title')}
              <Input value={posForm.title} onChange={(e) => setPosForm({ ...posForm, title: e.target.value })} />
            </label>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={closePosDialog}>{t('hr.common.cancel')}</Button>
              <Button onClick={() => savePosMutation.mutate()} disabled={!posForm.title || savePosMutation.isPending}>
                {savePosMutation.isPending ? t('hr.common.saving') : t('hr.common.save')}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </HRLayout>
  );
};

export default HRDepartments;
