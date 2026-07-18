import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { TasksLayout } from '@/components/tasks/TasksLayout';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from '@/components/ui/dialog';
import { toast } from 'sonner';
import { AlertCircle, Plus, Edit, Trash2, Truck } from 'lucide-react';
import {
  fetchEquipment, createEquipment, updateEquipment, deleteEquipment,
} from '@/api/tasks';
import type { Equipment } from '@/types/tasks';

const empty = { name: '', inventory_no: '', category: '' };

const HREquipment: React.FC = () => {
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<Equipment | null>(null);
  const [form, setForm] = useState(empty);

  const { data: equipment = [], isLoading, error } = useQuery({
    queryKey: ['equipment'],
    queryFn: () => fetchEquipment(true),
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['equipment'] });
    queryClient.invalidateQueries({ queryKey: ['resource-gantt'] });
  };

  const saveMutation = useMutation({
    mutationFn: (payload: typeof form) =>
      editing
        ? updateEquipment(editing.id, payload)
        : createEquipment(payload),
    onSuccess: () => {
      invalidate();
      setDialogOpen(false);
      toast.success(editing ? 'Техника обновлена' : 'Техника добавлена');
    },
    onError: () => toast.error('Не удалось сохранить'),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteEquipment(id),
    onSuccess: () => { invalidate(); toast.success('Техника удалена'); },
    onError: () => toast.error('Не удалось удалить'),
  });

  const openCreate = () => { setEditing(null); setForm(empty); setDialogOpen(true); };
  const openEdit = (e: Equipment) => {
    setEditing(e);
    setForm({ name: e.name, inventory_no: e.inventory_no ?? '', category: e.category ?? '' });
    setDialogOpen(true);
  };

  return (
    <TasksLayout title="Техника" subtitle="Справочник техники и оборудования">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0">
          <CardTitle className="flex items-center gap-2">
            <Truck className="h-5 w-5" /> Техника ({equipment.length})
          </CardTitle>
          <Button size="sm" onClick={openCreate}>
            <Plus className="h-4 w-4 mr-1" /> Добавить
          </Button>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="text-center py-8 text-muted-foreground">Загрузка...</div>
          ) : error ? (
            <div className="flex items-center gap-2 text-red-500 py-8 justify-center">
              <AlertCircle className="h-5 w-5" /> Ошибка загрузки
            </div>
          ) : equipment.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              Техника пока не добавлена. Нажмите «Добавить».
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Название</TableHead>
                  <TableHead className="w-[160px]">Инв. номер</TableHead>
                  <TableHead className="w-[200px]">Категория</TableHead>
                  <TableHead className="w-[100px] text-right">Действия</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {equipment.map((e) => (
                  <TableRow key={e.id}>
                    <TableCell className="font-medium">{e.name}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">{e.inventory_no || '—'}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">{e.category || '—'}</TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-1">
                        <Button size="icon" variant="ghost" className="h-7 w-7" onClick={() => openEdit(e)} title="Редактировать">
                          <Edit className="h-4 w-4" />
                        </Button>
                        <Button
                          size="icon" variant="ghost"
                          className="h-7 w-7 text-muted-foreground hover:text-destructive"
                          title="Удалить"
                          onClick={() => {
                            if (window.confirm(`Удалить «${e.name}»?`)) deleteMutation.mutate(e.id);
                          }}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editing ? 'Редактировать технику' : 'Новая техника'}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label>Название *</Label>
              <Input
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="Экскаватор CAT 320"
                className="mt-1"
              />
            </div>
            <div>
              <Label>Инвентарный / гос. номер</Label>
              <Input
                value={form.inventory_no}
                onChange={(e) => setForm({ ...form, inventory_no: e.target.value })}
                placeholder="EQ-001"
                className="mt-1"
              />
            </div>
            <div>
              <Label>Категория</Label>
              <Input
                value={form.category}
                onChange={(e) => setForm({ ...form, category: e.target.value })}
                placeholder="Спецтехника"
                className="mt-1"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>Отмена</Button>
            <Button
              onClick={() => saveMutation.mutate(form)}
              disabled={!form.name.trim() || saveMutation.isPending}
            >
              {editing ? 'Сохранить' : 'Добавить'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </TasksLayout>
  );
};

export default HREquipment;
