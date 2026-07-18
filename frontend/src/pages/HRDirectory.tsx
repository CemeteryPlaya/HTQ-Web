import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  fetchDepartments, fetchPositions,
  createDepartment, updateDepartment, deleteDepartment,
  createPosition, updatePosition, deletePosition,
} from '@/api/hr';
import type { Department, Position } from '@/types/hr';
import HRLayout from '@/components/hr/HRLayout';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
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
import { Building2, Plus, Pencil, Trash2, Loader2 } from 'lucide-react';

const HRDirectory = () => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const { data: departments = [] } = useQuery({
    queryKey: ['hr-departments'],
    queryFn: fetchDepartments,
  });

  const { data: positions = [] } = useQuery({
    queryKey: ['hr-positions'],
    queryFn: fetchPositions,
  });

  const [deptDialogOpen, setDeptDialogOpen] = useState(false);
  const [deptEditing, setDeptEditing] = useState<Department | null>(null);
  const [deptForm, setDeptForm] = useState({ name: '', description: '' });
  const [deptErrors, setDeptErrors] = useState<Record<string, string>>({});

  const [posDialogOpen, setPosDialogOpen] = useState(false);
  const [posEditing, setPosEditing] = useState<Position | null>(null);
  const [posForm, setPosForm] = useState({ title: '', department: '' });
  const [posErrors, setPosErrors] = useState<Record<string, string>>({});

  const [deleteTarget, setDeleteTarget] = useState<
    { type: 'department'; item: Department } | { type: 'position'; item: Position } | null
  >(null);

  const saveDepartment = useMutation({
    mutationFn: async () => {
      const payload = { name: deptForm.name.trim(), description: deptForm.description };
      if (deptEditing) return updateDepartment(deptEditing.id, payload);
      return createDepartment(payload);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hr-departments'] });
      setDeptDialogOpen(false);
      setDeptEditing(null);
      setDeptForm({ name: '', description: '' });
      setDeptErrors({});
    },
  });

  const savePosition = useMutation({
    mutationFn: async () => {
      const payload = {
        title: posForm.title.trim(),
        department: posForm.department ? Number(posForm.department) : null,
      };
      if (posEditing) return updatePosition(posEditing.id, payload);
      return createPosition(payload);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hr-positions'] });
      setPosDialogOpen(false);
      setPosEditing(null);
      setPosForm({ title: '', department: '' });
      setPosErrors({});
    },
  });

  const deleteMut = useMutation({
    mutationFn: async () => {
      if (!deleteTarget) return;
      if (deleteTarget.type === 'department') {
        return deleteDepartment(deleteTarget.item.id);
      }
      return deletePosition(deleteTarget.item.id);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hr-departments'] });
      queryClient.invalidateQueries({ queryKey: ['hr-positions'] });
      setDeleteTarget(null);
    },
  });

  const deleteLabel =
    deleteTarget?.type === 'department'
      ? deleteTarget.item.name
      : deleteTarget?.item.title;

  const openDeptCreate = () => {
    setDeptEditing(null);
    setDeptForm({ name: '', description: '' });
    setDeptErrors({});
    setDeptDialogOpen(true);
  };

  const openDeptEdit = (dept: Department) => {
    setDeptEditing(dept);
    setDeptForm({ name: dept.name, description: dept.description || '' });
    setDeptErrors({});
    setDeptDialogOpen(true);
  };

  const openPosCreate = () => {
    setPosEditing(null);
    setPosForm({ title: '', department: '' });
    setPosErrors({});
    setPosDialogOpen(true);
  };

  const openPosEdit = (pos: Position) => {
    setPosEditing(pos);
    setPosForm({ title: pos.title, department: pos.department ? String(pos.department) : '' });
    setPosErrors({});
    setPosDialogOpen(true);
  };

  const handleSaveDept = () => {
    const errs: Record<string, string> = {};
    if (!deptForm.name.trim()) errs.name = t('hr.directory.departmentRequired');
    setDeptErrors(errs);
    if (Object.keys(errs).length > 0) return;
    saveDepartment.mutate();
  };

  const handleSavePos = () => {
    const errs: Record<string, string> = {};
    if (!posForm.title.trim()) errs.title = t('hr.directory.positionRequired');
    setPosErrors(errs);
    if (Object.keys(errs).length > 0) return;
    savePosition.mutate();
  };

  return (
    <HRLayout>
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-lg bg-primary/10 flex items-center justify-center">
            <Building2 className="h-5 w-5 text-primary" />
          </div>
          <div>
            <h1 className="font-display text-2xl font-bold tracking-tight">{t('hr.directory.title')}</h1>
            <p className="text-sm text-muted-foreground">{t('hr.directory.subtitle')}</p>
          </div>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>{t('hr.directory.departmentsTitle')}</CardTitle>
            <Button onClick={openDeptCreate} className="gap-2" size="sm">
              <Plus className="h-4 w-4" /> {t('hr.directory.addDepartment')}
            </Button>
          </CardHeader>
          <CardContent>
            {departments.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t('hr.directory.emptyDepartments')}</p>
            ) : (
              <div className="bg-card rounded-lg border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t('hr.directory.departmentName')}</TableHead>
                      <TableHead>{t('hr.directory.description')}</TableHead>
                      <TableHead className="text-right">{t('hr.directory.actions')}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {departments.map((dept) => (
                      <TableRow key={dept.id}>
                        <TableCell className="font-medium">{dept.name}</TableCell>
                        <TableCell>{dept.description || '—'}</TableCell>
                        <TableCell className="text-right">
                          <div className="flex items-center justify-end gap-1">
                            <Button size="icon" variant="ghost" onClick={() => openDeptEdit(dept)}>
                              <Pencil className="h-4 w-4" />
                            </Button>
                            <Button
                              size="icon"
                              variant="ghost"
                              className="text-destructive"
                              onClick={() => setDeleteTarget({ type: 'department', item: dept })}
                            >
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
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>{t('hr.directory.positionsTitle')}</CardTitle>
            <Button onClick={openPosCreate} className="gap-2" size="sm" disabled={departments.length === 0}>
              <Plus className="h-4 w-4" /> {t('hr.directory.addPosition')}
            </Button>
          </CardHeader>
          <CardContent>
            {departments.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t('hr.directory.noDepartmentsHint')}</p>
            ) : positions.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t('hr.directory.emptyPositions')}</p>
            ) : (
              <div className="bg-card rounded-lg border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t('hr.directory.positionTitle')}</TableHead>
                      <TableHead>{t('hr.directory.department')}</TableHead>
                      <TableHead className="text-right">{t('hr.directory.actions')}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {positions.map((pos) => (
                      <TableRow key={pos.id}>
                        <TableCell className="font-medium">{pos.title}</TableCell>
                        <TableCell>{pos.department_name || '—'}</TableCell>
                        <TableCell className="text-right">
                          <div className="flex items-center justify-end gap-1">
                            <Button size="icon" variant="ghost" onClick={() => openPosEdit(pos)}>
                              <Pencil className="h-4 w-4" />
                            </Button>
                            <Button
                              size="icon"
                              variant="ghost"
                              className="text-destructive"
                              onClick={() => setDeleteTarget({ type: 'position', item: pos })}
                            >
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
          </CardContent>
        </Card>
      </div>

      {/* ============ Department Dialog ============ */}
      <Dialog open={deptDialogOpen} onOpenChange={setDeptDialogOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{deptEditing ? t('hr.directory.editDepartment') : t('hr.directory.addDepartment')}</DialogTitle>
            <DialogDescription>{t('hr.directory.departmentHint')}</DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <Label>{t('hr.directory.departmentName')}</Label>
              <Input value={deptForm.name} onChange={(e) => setDeptForm((f) => ({ ...f, name: e.target.value }))} />
              {deptErrors.name && <p className="text-xs text-destructive">{deptErrors.name}</p>}
            </div>
            <div className="grid gap-2">
              <Label>{t('hr.directory.description')}</Label>
              <Textarea
                value={deptForm.description}
                onChange={(e) => setDeptForm((f) => ({ ...f, description: e.target.value }))}
                rows={3}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeptDialogOpen(false)}>{t('hr.cancel')}</Button>
            <Button onClick={handleSaveDept} disabled={saveDepartment.isPending} className="gap-2">
              {saveDepartment.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              {t('hr.save')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ============ Position Dialog ============ */}
      <Dialog open={posDialogOpen} onOpenChange={setPosDialogOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{posEditing ? t('hr.directory.editPosition') : t('hr.directory.addPosition')}</DialogTitle>
            <DialogDescription>{t('hr.directory.positionHint')}</DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <Label>{t('hr.directory.positionTitle')}</Label>
              <Input value={posForm.title} onChange={(e) => setPosForm((f) => ({ ...f, title: e.target.value }))} />
              {posErrors.title && <p className="text-xs text-destructive">{posErrors.title}</p>}
            </div>
            <div className="grid gap-2">
              <Label>{t('hr.directory.department')}</Label>
              <Select value={posForm.department} onValueChange={(v) => setPosForm((f) => ({ ...f, department: v }))}>
                <SelectTrigger><SelectValue placeholder="—" /></SelectTrigger>
                <SelectContent>
                  {departments.map((dept) => (
                    <SelectItem key={dept.id} value={String(dept.id)}>{dept.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPosDialogOpen(false)}>{t('hr.cancel')}</Button>
            <Button onClick={handleSavePos} disabled={savePosition.isPending} className="gap-2">
              {savePosition.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              {t('hr.save')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ============ Delete confirmation ============ */}
      <AlertDialog open={!!deleteTarget} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('hr.deleteConfirmTitle')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('hr.deleteConfirmText', { name: deleteLabel })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('hr.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => deleteTarget && deleteMut.mutate()}
            >
              {t('hr.delete')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </HRLayout>
  );
};

export default HRDirectory;
