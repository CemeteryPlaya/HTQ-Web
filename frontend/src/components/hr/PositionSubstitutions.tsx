import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Calendar, Loader2, Plus, Trash2, X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

import { createSubstitution, deleteSubstitution, fetchSubstitutions, updateSubstitution, type Substitution, type SubstitutionInput, type SubstitutionKind } from '@/api/hr';
import { reportApiError } from '@/lib/apiError';
import { datesOutOfOrder } from '@/lib/validation';
import { todayIso } from '@/lib/dates';
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
import { DateInput } from '@/components/ui/date-input';
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogTitle } from '@/components/ui/alert-dialog';
import { translatedMap } from '@/lib/i18n/translatedMap';

interface PositionSubstitutionsProps {
  positionId: number;
  positions: Array<{ id: number; title: string; is_active?: boolean }>;
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
  const [closeTarget, setCloseTarget] = useState<{ id: number; validTo: string } | null>(null);
  const [formData, setFormData] = useState<SubstitutionInput>({
    substitute_position_id: 0,
    kind: 'primary',
    basis: '',
    note: null,
    valid_from: todayIso(),
    valid_to: null,
  });

  const { data: substitutions = [], isLoading } = useQuery({
    queryKey: ['hr', 'substitutions', positionId],
    queryFn: () => fetchSubstitutions(positionId),
  });

  useEffect(() => {
    if (!dialogOpen) {
      setFormData({
        substitute_position_id: 0,
        kind: 'primary',
        basis: '',
        note: null,
        valid_from: todayIso(),
        valid_to: null,
      });
    }
  }, [dialogOpen]);

  const createMutation = useMutation({
    mutationFn: (data: SubstitutionInput) => createSubstitution(positionId, data),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['hr', 'substitutions', positionId] });
      toast.success(t('hr.substitutions.created', 'Замещение добавлено'));
      setDialogOpen(false);
    },
    onError: (err) => {
      reportApiError(err, t('hr.substitutions.createFailed', 'Не удалось добавить замещение'));
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
      reportApiError(err, t('hr.substitutions.deleteFailed', 'Не удалось удалить замещение'));
    },
  });

  const closeMutation = useMutation({
    mutationFn: ({ id, validTo }: { id: number; validTo: string }) =>
      updateSubstitution(id, { valid_to: validTo }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['hr', 'substitutions', positionId] });
      toast.success(t('hr.substitutions.closed', 'Замещение закрыто'));
      setCloseTarget(null);
    },
    onError: (err) => {
      reportApiError(err, t('hr.substitutions.closeFailed', 'Не удалось закрыть замещение'));
    },
  });

  // Границы ВКЛЮЧИТЕЛЬНЫЕ на бэкенде (substitution_service): правило,
  // действующее ПО дате X, всё ещё действует В день X. Сравниваем ISO-строки
  // `ГГГГ-ММ-ДД`, а не `new Date(...)`, — иначе `substitutes_for` ещё
  // возвращает строку, а бейдж загорается с полуночи UTC (05:00 по Алматы).
  const isExpired = (validTo: string | null): boolean => {
    if (!validTo) return false;
    return validTo < todayIso();
  };

  const formatDateRange = (from: string, to: string | null): string => {
    if (!to) return `${from} — ${t('hr.substitutions.indefinite', 'бессрочно')}`;
    return `${from} — ${to}`;
  };

  // Неактивную должность в матрицу не назначить: substitutes_for её не
  // вернёт (substitution_service.active_for_position), и правило выглядело
  // бы действующим, а маршрут согласования звал бы некого.
  const availablePositions = positions.filter((p) => p.id !== positionId && p.is_active !== false);

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
            // Неактивная должность правило не прикроет: substitutes_for её
            // не вернёт (active_for_position фильтрует по is_active), а
            // строка на карточке выглядела бы как действующая.
            const substituteInactive = positions.find(
              (p) => p.id === sub.substitute_position_id,
            )?.is_active === false;

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
                      {substituteInactive && (
                        <Badge variant="outline" className="text-xs">
                          {t('hr.substitutions.inactivePosition', 'должность неактивна')}
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
                  <div className="flex items-center gap-1">
                    {sub.valid_to === null && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setCloseTarget({ id: sub.id, validTo: todayIso() })}
                        disabled={closeMutation.isPending}
                        aria-label={t('hr.substitutions.closeAction', 'Закрыть замещение')}
                        title={t('hr.substitutions.closeAction', 'Закрыть замещение')}
                      >
                        <X className="h-4 w-4" />
                      </Button>
                    )}
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
                <DateInput
                  id="valid-from"
                  value={formData.valid_from}
                  onChange={(v) => setFormData({ ...formData, valid_from: v })}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="valid-to" className="text-sm">
                  {t('hr.substitutions.validTo', 'Дата окончания')}
                </Label>
                <DateInput
                  id="valid-to"
                  value={formData.valid_to ?? ''}
                  onChange={(v) => setFormData({ ...formData, valid_to: v || null })}
                  invalid={datesOutOfOrder(formData.valid_from, formData.valid_to)}
                />
              </div>
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>
              {t('common.cancel', 'Отмена')}
            </Button>
            <Button
              onClick={() => {
                if (datesOutOfOrder(formData.valid_from, formData.valid_to)) {
                  toast.error(t('validation.datesOutOfOrder', 'Дата начала позже даты окончания'));
                  return;
                }
                createMutation.mutate(formData);
              }}
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

      {/* Диалог закрытия бессрочного замещения */}
      <Dialog open={closeTarget !== null} onOpenChange={(open) => !open && setCloseTarget(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{t('hr.substitutions.closeTitle', 'Закрыть замещение?')}</DialogTitle>
            <DialogDescription>
              {t('hr.substitutions.closeHint', 'Укажите дату окончания действия правила')}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-2">
            <Label htmlFor="close-valid-to" className="text-sm">
              {t('hr.substitutions.validTo', 'Дата окончания')}
            </Label>
            <DateInput
              id="close-valid-to"
              value={closeTarget?.validTo ?? ''}
              onChange={(v) => closeTarget && setCloseTarget({ ...closeTarget, validTo: v })}
            />
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setCloseTarget(null)}>
              {t('common.cancel', 'Отмена')}
            </Button>
            <Button
              onClick={() => {
                if (closeTarget) closeMutation.mutate({ id: closeTarget.id, validTo: closeTarget.validTo });
              }}
              disabled={!closeTarget?.validTo || closeMutation.isPending}
            >
              {closeMutation.isPending ? t('common.saving', 'Сохранение…') : t('hr.substitutions.close', 'Закрыть')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default PositionSubstitutions;
