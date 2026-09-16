import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Calendar, Loader2, Plus, Trash2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

import { createSubstitution, deleteSubstitution, fetchSubstitutions, type Substitution, type SubstitutionInput, type SubstitutionKind } from '@/api/hr';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogTitle } from '@/components/ui/alert-dialog';
import { translatedMap } from '@/lib/i18n/translatedMap';

interface PositionSubstitutionsProps {
  positionId: number;
  positions: Array<{ id: number; title: string }>;
}

const KIND_LABELS = translatedMap<SubstitutionKind>({
  primary: 'hr.substitutions.kindPrimary',
  reserve: 'hr.substitutions.kindReserve',
});

export function PositionSubstitutions({ positionId, positions }: PositionSubstitutionsProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState<number | null>(null);
  const [formData, setFormData] = useState<SubstitutionInput>({
    substitute_position_id: 0,
    kind: 'primary',
    basis: '',
    note: null,
    valid_from: new Date().toISOString().split('T')[0],
    valid_to: null,
  });

  const { data: substitutions = [], isLoading } = useQuery({
    queryKey: ['hr', 'substitutions', positionId],
    queryFn: () => fetchSubstitutions(positionId),
  });

  const [createError, setCreateError] = useState<string | null>(null);

  useEffect(() => {
    if (!dialogOpen) {
      setFormData({
        substitute_position_id: 0,
        kind: 'primary',
        basis: '',
        note: null,
        valid_from: new Date().toISOString().split('T')[0],
        valid_to: null,
      });
      setCreateError(null);
    }
  }, [dialogOpen]);

  const createMutation = useMutation({
    mutationFn: (data: SubstitutionInput) => createSubstitution(positionId, data),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['hr', 'substitutions', positionId] });
      toast.success(t('hr.substitutions.created', 'Замещение добавлено'));
      setDialogOpen(false);
      setCreateError(null);
    },
    onError: (err) => {
      const errorMsg = (err as any)?.response?.data?.detail
        ?? t('hr.substitutions.createFailed', 'Не удалось добавить замещение');
      setCreateError(errorMsg);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteSubstitution(id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['hr', 'substitutions', positionId] });
      toast.success(t('hr.substitutions.deleted', 'Замещение удалено'));
      setDeleteConfirm(null);
    },
    onError: (err) => {
      const errorMsg = (err as any)?.response?.data?.detail
        ?? t('hr.substitutions.deleteFailed', 'Не удалось удалить замещение');
      toast.error(errorMsg);
    },
  });

  const isExpired = (validTo: string | null): boolean => {
    if (!validTo) return false;
    return new Date(validTo) < new Date();
  };

  const formatDateRange = (from: string, to: string | null): string => {
    if (!to) return `${from} — ${t('hr.substitutions.indefinite', 'бессрочно')}`;
    return `${from} — ${to}`;
  };

  const availablePositions = positions.filter((p) => p.id !== positionId);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium">{t('hr.substitutions.title', 'Замещение')}</h3>
        <Button
          variant="outline"
          size="sm"
          onClick={() => setDialogOpen(true)}
          disabled={isLoading}
        >
          <Plus className="h-4 w-4" />
          {t('hr.substitutions.add', 'Добавить')}
        </Button>
      </div>

      <p className="text-xs text-muted-foreground">
        {t('hr.substitutions.hint', 'Матрица замещения утверждается приказом и действует в маршрутах согласования')}
      </p>

      {isLoading ? (
        <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t('common.loading', 'Загрузка…')}
        </div>
      ) : substitutions.length === 0 ? (
        <div className="rounded-md bg-muted px-3 py-2 text-sm text-muted-foreground">
          {t('hr.substitutions.empty', 'Замещающих не назначено')}
        </div>
      ) : (
        <div className="space-y-2">
          {substitutions.map((sub) => {
            const expired = isExpired(sub.valid_to);
            const substitutePos = positions.find((p) => p.id === sub.substitute_position_id);

            return (
              <div
                key={sub.id}
                className={`rounded-md border p-3 ${expired ? 'bg-muted opacity-60' : 'bg-card'}`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-medium text-sm">{sub.substitute_position_title}</span>
                      <Badge variant="secondary" className="text-xs">
                        {KIND_LABELS[sub.kind]}
                      </Badge>
                      {expired && (
                        <Badge variant="destructive" className="text-xs">
                          {t('hr.substitutions.expired', 'истекло')}
                        </Badge>
                      )}
                    </div>
                    <div className="mt-1 space-y-1 text-xs text-muted-foreground">
                      <div>
                        <span className="font-medium">{t('hr.substitutions.basis', 'Основание')}:</span> {sub.basis}
                      </div>
                      {sub.note && (
                        <div>
                          <span className="font-medium">{t('hr.substitutions.note', 'Примечание')}:</span> {sub.note}
                        </div>
                      )}
                      <div className="flex items-center gap-1">
                        <Calendar className="h-3 w-3" />
                        {formatDateRange(sub.valid_from, sub.valid_to)}
                      </div>
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setDeleteConfirm(sub.id)}
                    disabled={deleteMutation.isPending}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Диалог добавления */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{t('hr.substitutions.addTitle', 'Добавить замещение')}</DialogTitle>
            <DialogDescription>
              {t('hr.substitutions.addHint', 'Выберите должность замещающего и период действия')}
            </DialogDescription>
          </DialogHeader>

          {createError && (
            <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {createError}
            </div>
          )}

          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="substitute-pos" className="text-sm">
                {t('hr.substitutions.substitutePosition', 'Замещающая должность')}
              </Label>
              <Select
                value={String(formData.substitute_position_id)}
                onValueChange={(v) => setFormData({ ...formData, substitute_position_id: Number(v) })}
              >
                <SelectTrigger id="substitute-pos">
                  <SelectValue placeholder={t('hr.substitutions.selectPosition', 'Выберите должность')} />
                </SelectTrigger>
                <SelectContent>
                  {availablePositions.map((pos) => (
                    <SelectItem key={pos.id} value={String(pos.id)}>
                      {pos.title}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="kind" className="text-sm">
                {t('hr.substitutions.kind', 'Вид')}
              </Label>
              <Select
                value={formData.kind}
                onValueChange={(v) => setFormData({ ...formData, kind: v as SubstitutionKind })}
              >
                <SelectTrigger id="kind">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="primary">{KIND_LABELS.primary}</SelectItem>
                  <SelectItem value="reserve">{KIND_LABELS.reserve}</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="basis" className="text-sm">
                {t('hr.substitutions.basis', 'Основание')} *
              </Label>
              <Input
                id="basis"
                placeholder={t('hr.substitutions.basisPlaceholder', 'Приказ ГД, доверенность…')}
                value={formData.basis}
                onChange={(e) => setFormData({ ...formData, basis: e.target.value })}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="note" className="text-sm">
                {t('hr.substitutions.note', 'Примечание')}
              </Label>
              <Textarea
                id="note"
                placeholder={t('hr.substitutions.notePlaceholder', 'Право первой подписи, ограничения…')}
                value={formData.note ?? ''}
                onChange={(e) => setFormData({ ...formData, note: e.target.value || null })}
                className="min-h-[80px]"
              />
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-2">
                <Label htmlFor="valid-from" className="text-sm">
                  {t('hr.substitutions.validFrom', 'Дата начала')}
                </Label>
                <Input
                  id="valid-from"
                  type="date"
                  value={formData.valid_from}
                  onChange={(e) => setFormData({ ...formData, valid_from: e.target.value })}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="valid-to" className="text-sm">
                  {t('hr.substitutions.validTo', 'Дата окончания')}
                </Label>
                <Input
                  id="valid-to"
                  type="date"
                  value={formData.valid_to ?? ''}
                  onChange={(e) => setFormData({ ...formData, valid_to: e.target.value || null })}
                />
              </div>
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>
              {t('common.cancel', 'Отмена')}
            </Button>
            <Button
              onClick={() => createMutation.mutate(formData)}
              disabled={!formData.substitute_position_id || !formData.basis || createMutation.isPending}
            >
              {createMutation.isPending ? t('common.saving', 'Сохранение…') : t('common.save', 'Сохранить')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Диалог подтверждения удаления */}
      <AlertDialog open={deleteConfirm !== null} onOpenChange={(open) => !open && setDeleteConfirm(null)}>
        <AlertDialogContent>
          <AlertDialogTitle>{t('hr.substitutions.deleteConfirmTitle', 'Удалить замещение?')}</AlertDialogTitle>
          <AlertDialogDescription>
            {t('hr.substitutions.deleteConfirmDesc', 'Это действие нельзя отменить')}
          </AlertDialogDescription>
          <div className="flex justify-end gap-2">
            <AlertDialogCancel>{t('common.cancel', 'Отмена')}</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (deleteConfirm !== null) {
                  deleteMutation.mutate(deleteConfirm);
                }
              }}
              disabled={deleteMutation.isPending}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {t('common.delete', 'Удалить')}
            </AlertDialogAction>
          </div>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

export default PositionSubstitutions;
