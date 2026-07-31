import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { TasksLayout } from '@/components/tasks/TasksLayout';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Badge } from '@/components/ui/badge';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from '@/components/ui/dialog';
import { toast } from 'sonner';
import { AlertCircle, Plus, Edit, PowerOff, RotateCcw, Truck } from 'lucide-react';
import {
  fetchEquipment, createEquipment, updateEquipment, deleteEquipment,
  fetchContractors, fetchEquipmentCategories,
} from '@/api/tasks';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import type { Equipment, EquipmentOwnership } from '@/types/tasks';

const OWNERSHIPS: EquipmentOwnership[] = ['own', 'contractor', 'rented'];

const empty = {
  name: '', inventory_no: '', category: '',
  ownership: 'own' as EquipmentOwnership, contractor_id: '',
};

const HREquipment: React.FC = () => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<Equipment | null>(null);
  const [form, setForm] = useState(empty);
  // DELETE on this register is a soft disable on the backend (historical
  // assignments reference the row). The page used to request active-only
  // and never offer anything else, so a disabled machine vanished with no
  // way back — you had to go into django-admin to undo a misclick.
  const [showDisabled, setShowDisabled] = useState(false);
  const [ownershipFilter, setOwnershipFilter] = useState<string>('all');

  const { data: equipment = [], isLoading, error } = useQuery({
    queryKey: ['equipment', { showDisabled, ownershipFilter }],
    queryFn: () => fetchEquipment(!showDisabled, {
      ownership: ownershipFilter === 'all' ? undefined : ownershipFilter,
    }),
  });

  const { data: contractors = [] } = useQuery({
    queryKey: ['contractors'],
    queryFn: () => fetchContractors({ status: 'active' }),
  });

  const { data: categories = [] } = useQuery({
    queryKey: ['equipment-categories'],
    queryFn: () => fetchEquipmentCategories(),
  });

  const ownershipLabel = (o: EquipmentOwnership) =>
    t('tasks.pages.equipment.ownership.' + o, o);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['equipment'] });
    queryClient.invalidateQueries({ queryKey: ['resource-gantt'] });
  };

  const saveMutation = useMutation({
    mutationFn: (payload: typeof form) => {
      const body: Partial<Equipment> = {
        name: payload.name,
        inventory_no: payload.inventory_no,
        category: payload.category,
        ownership: payload.ownership,
        // Подрядчик имеет смысл только для его же техники: у собственной и
        // арендованной он всегда пуст, иначе CHECK на бэкенде отвергнет.
        contractor_id: payload.ownership === 'contractor' && payload.contractor_id
          ? Number(payload.contractor_id)
          : null,
      };
      return editing ? updateEquipment(editing.id, body) : createEquipment(body);
    },
    onSuccess: () => {
      invalidate();
      setDialogOpen(false);
      toast.success(editing
        ? t('tasks.pages.equipment.updated', 'Техника обновлена')
        : t('tasks.pages.equipment.created', 'Техника добавлена'));
    },
    onError: () => toast.error(t('tasks.pages.equipment.saveError', 'Не удалось сохранить')),
  });

  const disableMutation = useMutation({
    mutationFn: (id: number) => deleteEquipment(id),
    onSuccess: () => {
      invalidate();
      toast.success(t('tasks.pages.equipment.disabled', 'Техника отключена'));
    },
    onError: () => toast.error(t('tasks.pages.equipment.disableError', 'Не удалось отключить')),
  });

  const restoreMutation = useMutation({
    mutationFn: (id: number) => updateEquipment(id, { is_active: true }),
    onSuccess: () => {
      invalidate();
      toast.success(t('tasks.pages.equipment.restored', 'Техника возвращена в работу'));
    },
    onError: () => toast.error(t('tasks.pages.equipment.restoreError', 'Не удалось вернуть')),
  });

  const openCreate = () => { setEditing(null); setForm(empty); setDialogOpen(true); };
  const openEdit = (e: Equipment) => {
    setEditing(e);
    setForm({
      name: e.name,
      inventory_no: e.inventory_no ?? '',
      category: e.category ?? '',
      ownership: e.ownership,
      contractor_id: e.contractor_id ? String(e.contractor_id) : '',
    });
    setDialogOpen(true);
  };

  return (
    <TasksLayout
      title={t('tasks.pages.equipment.title', 'Техника')}
      subtitle={t('tasks.pages.equipment.subtitle', 'Справочник техники и оборудования')}
    >
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 gap-4">
          <CardTitle className="flex items-center gap-2">
            <Truck className="h-5 w-5" />
            {t('tasks.pages.equipment.title', 'Техника')} ({equipment.length})
          </CardTitle>
          <div className="flex items-center gap-4">
            <Select value={ownershipFilter} onValueChange={setOwnershipFilter}>
              <SelectTrigger className="h-9 w-[190px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">
                  {t('tasks.pages.equipment.allOwnerships', 'Вся техника')}
                </SelectItem>
                {OWNERSHIPS.map((o) => (
                  <SelectItem key={o} value={o}>{ownershipLabel(o)}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <label className="flex items-center gap-2 text-sm text-muted-foreground cursor-pointer">
              <Switch checked={showDisabled} onCheckedChange={setShowDisabled} />
              {t('tasks.pages.equipment.showDisabled', 'Показать отключённые')}
            </label>
            <Button size="sm" onClick={openCreate}>
              <Plus className="h-4 w-4 mr-1" /> {t('common.add', 'Добавить')}
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="text-center py-8 text-muted-foreground">
              {t('common.loading', 'Загрузка...')}
            </div>
          ) : error ? (
            <div className="flex items-center gap-2 text-red-500 py-8 justify-center">
              <AlertCircle className="h-5 w-5" />
              {t('tasks.pages.equipment.loadError', 'Ошибка загрузки')}
            </div>
          ) : equipment.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              {t('tasks.pages.equipment.empty', 'Техника пока не добавлена. Нажмите «Добавить».')}
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('tasks.pages.equipment.name', 'Название')}</TableHead>
                  <TableHead className="w-[160px]">
                    {t('tasks.pages.equipment.inventoryNo', 'Инв. номер')}
                  </TableHead>
                  <TableHead className="w-[200px]">
                    {t('tasks.pages.equipment.category', 'Категория')}
                  </TableHead>
                  <TableHead className="w-[190px]">
                    {t('tasks.pages.equipment.owner', 'Владелец')}
                  </TableHead>
                  <TableHead className="w-[110px] text-right">
                    {t('common.actions', 'Действия')}
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {equipment.map((e) => (
                  <TableRow key={e.id} className={e.is_active ? undefined : 'opacity-60'}>
                    <TableCell className="font-medium">
                      <span className="inline-flex items-center gap-2">
                        {e.name}
                        {!e.is_active && (
                          <Badge variant="outline" className="font-normal">
                            {t('tasks.pages.equipment.disabledBadge', 'отключена')}
                          </Badge>
                        )}
                      </span>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">{e.inventory_no || '—'}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">{e.category || '—'}</TableCell>
                    <TableCell className="text-sm">
                      <span className="text-muted-foreground">
                        {ownershipLabel(e.ownership)}
                      </span>
                      {e.contractor_name && (
                        <span className="block text-xs text-muted-foreground truncate">
                          {e.contractor_name}
                        </span>
                      )}
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-1">
                        <Button
                          size="icon" variant="ghost" className="h-7 w-7"
                          onClick={() => openEdit(e)}
                          title={t('common.edit', 'Редактировать')}
                        >
                          <Edit className="h-4 w-4" />
                        </Button>
                        {e.is_active ? (
                          <Button
                            size="icon" variant="ghost"
                            className="h-7 w-7 text-muted-foreground hover:text-destructive"
                            title={t('tasks.pages.equipment.disable', 'Отключить')}
                            onClick={() => {
                              if (window.confirm(t(
                                'tasks.pages.equipment.disableConfirm',
                                'Отключить «{{name}}»? Техника скроется из планирования, но останется в истории назначений.',
                                { name: e.name },
                              ))) disableMutation.mutate(e.id);
                            }}
                          >
                            <PowerOff className="h-4 w-4" />
                          </Button>
                        ) : (
                          <Button
                            size="icon" variant="ghost"
                            className="h-7 w-7 text-muted-foreground hover:text-primary"
                            title={t('tasks.pages.equipment.restore', 'Вернуть в работу')}
                            onClick={() => restoreMutation.mutate(e.id)}
                          >
                            <RotateCcw className="h-4 w-4" />
                          </Button>
                        )}
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
            <DialogTitle>
              {editing
                ? t('tasks.pages.equipment.editTitle', 'Редактировать технику')
                : t('tasks.pages.equipment.newTitle', 'Новая техника')}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label>{t('tasks.pages.equipment.name', 'Название')} *</Label>
              <Input
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder={t('tasks.pages.equipment.namePlaceholder', 'Экскаватор CAT 320')}
                className="mt-1"
              />
            </div>
            <div>
              <Label>{t('tasks.pages.equipment.inventoryNoFull', 'Инвентарный / гос. номер')}</Label>
              <Input
                value={form.inventory_no}
                onChange={(e) => setForm({ ...form, inventory_no: e.target.value })}
                placeholder="EQ-001"
                className="mt-1"
              />
            </div>
            <div>
              <Label>{t('tasks.pages.equipment.category', 'Категория')}</Label>
              {/* Ввод с подсказкой, а не закрытый список: за полем теперь
                  справочник EquipmentCategory, но «купили машину нового
                  типа» — законный админский сценарий, и бэкенд заводит
                  строку по имени сам. Datalist даёт и то и другое; чистый
                  Select отнял бы второе. */}
              <Input
                value={form.category}
                list="equipment-categories"
                onChange={(e) => setForm({ ...form, category: e.target.value })}
                placeholder={t('tasks.pages.equipment.categoryPlaceholder', 'Спецтехника')}
                className="mt-1"
              />
              <datalist id="equipment-categories">
                {categories.map((row) => (
                  <option key={row.id} value={row.name} />
                ))}
              </datalist>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label>{t('tasks.pages.equipment.owner', 'Владелец')}</Label>
                <Select
                  value={form.ownership}
                  onValueChange={(v) => setForm({
                    ...form,
                    ownership: v as EquipmentOwnership,
                    // Смена владельца на собственную или аренду очищает
                    // подрядчика: иначе форма отправит противоречивую пару.
                    contractor_id: v === 'contractor' ? form.contractor_id : '',
                  })}
                >
                  <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {OWNERSHIPS.map((o) => (
                      <SelectItem key={o} value={o}>{ownershipLabel(o)}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              {form.ownership === 'contractor' && (
                <div>
                  <Label>{t('tasks.pages.contractors.one', 'Подрядчик')} *</Label>
                  <Select
                    value={form.contractor_id}
                    onValueChange={(v) => setForm({ ...form, contractor_id: v })}
                  >
                    <SelectTrigger className="mt-1">
                      <SelectValue placeholder={t('tasks.pages.contractors.select', 'Выбрать')} />
                    </SelectTrigger>
                    <SelectContent>
                      {contractors.map((c) => (
                        <SelectItem key={c.id} value={String(c.id)}>{c.name}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              )}
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>
              {t('common.cancel', 'Отмена')}
            </Button>
            <Button
              onClick={() => saveMutation.mutate(form)}
              disabled={!form.name.trim() || saveMutation.isPending
                || (form.ownership === 'contractor' && !form.contractor_id)}
            >
              {editing ? t('common.save', 'Сохранить') : t('common.add', 'Добавить')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </TasksLayout>
  );
};

export default HREquipment;
