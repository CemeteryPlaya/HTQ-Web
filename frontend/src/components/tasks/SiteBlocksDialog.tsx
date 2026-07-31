/**
 * SiteBlocksDialog — блоки объекта и их плановые объёмы.
 *
 * Блок это участок площадки («Сазаган → блок 1, блок 2»), по которому
 * реально ведут работы. Плановый объём на блоке («250 валов») — то, ради
 * чего блок и заведён: он даёт считать выполнение в штуках, а не в
 * статусах задач.
 *
 * Объёмы отправляются заменой набора целиком (`PUT .../volumes`) — сервер
 * разницу не вычисляет, и форма не должна её вычислять тоже.
 */
import React, { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Plus, Trash2 } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { toast } from 'sonner';
import {
  createSiteBlock, deleteSiteBlock, fetchSiteBlocks, fetchVolumeTypes,
  setBlockVolumes, updateSiteBlock,
} from '@/api/tasks';
import {
  BLOCK_STATUS_ORDER, blockStatusBadgeClass, blockStatusLabel, volumeUnitLabel,
} from '@/lib/tasks/roadmap';
import type { BlockStatus, Site, SiteBlock } from '@/types/tasks';

interface VolumeDraft {
  volume_type_id: number | null;
  planned_quantity: string;
}

const emptyBlock = {
  name: '', code: '', order: 0, status: 'planned' as BlockStatus,
  start_date: '', end_date: '',
};

export const SiteBlocksDialog: React.FC<{
  site: Site | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}> = ({ site, open, onOpenChange }) => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const [editing, setEditing] = useState<SiteBlock | null>(null);
  const [form, setForm] = useState(emptyBlock);
  const [volumes, setVolumes] = useState<VolumeDraft[]>([]);

  const { data: blocks = [], isLoading } = useQuery({
    queryKey: ['site-blocks', site?.id],
    queryFn: () => fetchSiteBlocks(site!.id),
    enabled: open && !!site,
  });
  const { data: volumeTypes = [] } = useQuery({
    queryKey: ['volume-types'],
    queryFn: () => fetchVolumeTypes(),
    enabled: open,
  });

  // Закрытие диалога сбрасывает черновик: иначе следующий объект
  // открывался бы с наполовину заполненной формой предыдущего.
  useEffect(() => {
    if (!open) {
      setEditing(null);
      setForm(emptyBlock);
      setVolumes([]);
    }
  }, [open]);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['site-blocks', site?.id] });
    queryClient.invalidateQueries({ queryKey: ['hr-tasks'] });
  };

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!site) return;
      const payload = {
        name: form.name.trim(),
        code: form.code.trim() || null,
        order: Number(form.order) || 0,
        status: form.status,
        start_date: form.start_date || null,
        end_date: form.end_date || null,
      };
      const block = editing
        ? await updateSiteBlock(editing.id, payload)
        : await createSiteBlock(site.id, payload);

      const rows = volumes
        .filter((v) => v.volume_type_id !== null && v.planned_quantity !== '')
        .map((v) => ({
          volume_type_id: v.volume_type_id as number,
          planned_quantity: Number(v.planned_quantity),
        }));
      // PUT и на пустом списке: так снимается последний объём, который
      // иначе остался бы висеть после удаления строки в форме.
      await setBlockVolumes(block.id, rows);
    },
    onSuccess: () => {
      toast.success(editing
        ? t('tasks.pages.blocks.updated', 'Блок обновлён')
        : t('tasks.pages.blocks.created', 'Блок создан'));
      setEditing(null);
      setForm(emptyBlock);
      setVolumes([]);
      invalidate();
    },
    onError: () => toast.error(
      t('tasks.pages.blocks.saveError', 'Не удалось сохранить блок')),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteSiteBlock(id),
    onSuccess: () => {
      toast.success(t('tasks.pages.blocks.deleted', 'Блок удалён'));
      invalidate();
    },
    onError: () => toast.error(
      t('tasks.pages.blocks.deleteError', 'Не удалось удалить блок')),
  });

  const openEdit = (block: SiteBlock) => {
    setEditing(block);
    setForm({
      name: block.name,
      code: block.code ?? '',
      order: block.order,
      status: block.status,
      start_date: block.start_date ?? '',
      end_date: block.end_date ?? '',
    });
    setVolumes(block.volumes.map((v) => ({
      volume_type_id: v.volume_type_id,
      planned_quantity: String(v.planned_quantity),
    })));
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {t('tasks.pages.blocks.title', 'Блоки объекта')}
            {site && <span className="text-muted-foreground"> — {site.name}</span>}
          </DialogTitle>
        </DialogHeader>

        {/* Существующие блоки */}
        <div className="space-y-2">
          {isLoading ? (
            <p className="text-sm text-muted-foreground">
              {t('common.loading', 'Загрузка...')}
            </p>
          ) : blocks.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {t('tasks.pages.blocks.empty', 'Блоков пока нет')}
            </p>
          ) : blocks.map((block) => (
            <div
              key={block.id}
              className="flex items-center gap-2 rounded-md border p-2 text-sm"
            >
              <span className="font-medium flex-1 truncate">{block.name}</span>
              <Badge className={blockStatusBadgeClass(block.status)} variant="secondary">
                {blockStatusLabel(block.status, t)}
              </Badge>
              <span className="text-xs text-muted-foreground">
                {block.volumes.length === 0
                  ? t('tasks.pages.blocks.noVolumes', 'Объёмы не заданы')
                  : block.volumes
                    .map((v) => `${v.volume_type_name}: ${v.planned_quantity} ${volumeUnitLabel(v.unit)}`)
                    .join(', ')}
              </span>
              <Button size="sm" variant="ghost" className="h-7"
                      onClick={() => openEdit(block)}>
                {t('common.edit', 'Редактировать')}
              </Button>
              <Button
                size="icon" variant="ghost"
                className="h-7 w-7 text-muted-foreground hover:text-destructive"
                onClick={() => {
                  if (window.confirm(t('tasks.pages.blocks.deleteConfirm', 'Удалить блок?'))) {
                    deleteMutation.mutate(block.id);
                  }
                }}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          ))}
        </div>

        {/* Форма блока */}
        <div className="border-t pt-4 space-y-3">
          <p className="text-sm font-medium">
            {editing
              ? t('tasks.pages.blocks.editTitle', 'Блок')
              : t('tasks.pages.blocks.newTitle', 'Новый блок')}
          </p>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>{t('tasks.pages.blocks.name', 'Название')}</Label>
              <Input
                value={form.name}
                placeholder={t('tasks.pages.blocks.namePlaceholder', 'Блок 1')}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
              />
            </div>
            <div>
              <Label>{t('tasks.pages.blocks.code', 'Код')}</Label>
              <Input
                value={form.code}
                onChange={(e) => setForm({ ...form, code: e.target.value })}
              />
            </div>
            <div>
              <Label>{t('tasks.pages.blocks.order', 'Порядок')}</Label>
              <Input
                type="number" min={0} value={form.order}
                onChange={(e) => setForm({ ...form, order: Number(e.target.value) })}
              />
            </div>
            <div>
              <Label>{t('tasks.blocks.status.title', 'Статус')}</Label>
              <Select
                value={form.status}
                onValueChange={(v) => setForm({ ...form, status: v as BlockStatus })}
              >
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {BLOCK_STATUS_ORDER.map((status) => (
                    <SelectItem key={status} value={status}>
                      {blockStatusLabel(status, t)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>{t('tasks.pages.blocks.start', 'Начало')}</Label>
              <Input
                type="date" value={form.start_date}
                onChange={(e) => setForm({ ...form, start_date: e.target.value })}
              />
            </div>
            <div>
              <Label>{t('tasks.pages.blocks.end', 'Окончание')}</Label>
              <Input
                type="date" value={form.end_date}
                onChange={(e) => setForm({ ...form, end_date: e.target.value })}
              />
            </div>
          </div>

          {/* Плановые объёмы */}
          <div>
            <Label>{t('tasks.pages.blocks.volumes', 'Объёмы работ')}</Label>
            <div className="space-y-2 mt-1">
              {volumes.map((row, index) => (
                <div key={index} className="flex items-center gap-2">
                  <Select
                    value={row.volume_type_id ? String(row.volume_type_id) : ''}
                    onValueChange={(v) => setVolumes(volumes.map((item, i) =>
                      i === index ? { ...item, volume_type_id: Number(v) } : item))}
                  >
                    <SelectTrigger className="flex-1">
                      <SelectValue
                        placeholder={t('tasks.pages.blocks.volumeType', 'Вид работ')}
                      />
                    </SelectTrigger>
                    <SelectContent>
                      {volumeTypes.map((type) => (
                        <SelectItem key={type.id} value={String(type.id)}>
                          {type.name} ({volumeUnitLabel(type.unit)})
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Input
                    type="number" min={0} step="0.01" className="w-32"
                    placeholder={t('tasks.pages.blocks.planned', 'План')}
                    value={row.planned_quantity}
                    onChange={(e) => setVolumes(volumes.map((item, i) =>
                      i === index ? { ...item, planned_quantity: e.target.value } : item))}
                  />
                  <Button
                    size="icon" variant="ghost" className="h-8 w-8"
                    onClick={() => setVolumes(volumes.filter((_, i) => i !== index))}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              ))}
              <Button
                size="sm" variant="outline"
                onClick={() => setVolumes([
                  ...volumes, { volume_type_id: null, planned_quantity: '' },
                ])}
              >
                <Plus className="h-4 w-4 mr-1" />
                {t('tasks.pages.blocks.addVolume', 'Добавить объём')}
              </Button>
            </div>
          </div>
        </div>

        <DialogFooter>
          {editing && (
            <Button
              variant="outline"
              onClick={() => { setEditing(null); setForm(emptyBlock); setVolumes([]); }}
            >
              {t('common.cancel', 'Отмена')}
            </Button>
          )}
          <Button
            disabled={!form.name.trim() || saveMutation.isPending}
            onClick={() => saveMutation.mutate()}
          >
            {editing
              ? t('common.save', 'Сохранить')
              : t('tasks.pages.blocks.create', 'Новый блок')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

export default SiteBlocksDialog;
