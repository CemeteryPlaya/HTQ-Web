/**
 * CardT2SectionDialog — правка ОДНОЙ секции Т-2 карточки сотрудника.
 *
 * Секции («Финансы», «Личные данные», «СРО и охрана труда») закрыты
 * посекционным RBAC на бэкенде: `hr.card.<section>.view` — читать,
 * `hr.card.<section>.edit` — писать. Кнопку правки показывает вызывающий
 * (HREmployeeCard) по edit-ключу; здесь дублируется только валидация формата,
 * право проверяет бэкенд.
 *
 * ПОЧЕМУ ПО ОДНОЙ СЕКЦИИ. `employee_card_t2_service.upsert` применяет патч
 * целиком или никак: отказ прав на любой из секций откатывает и уже
 * применённые. Общая форма на три секции означала бы, что отказ на «Финансах»
 * молча теряет правки «Личных данных», — поэтому каждая секция сохраняется
 * отдельным запросом.
 *
 * Пустое поле уходит как `null`, а не пустой строкой: `birth_date` и прочие
 * даты у Pydantic — `date | None`, и `""` вернул бы 422.
 */
import { useEffect, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

import { updateCardT2, type CardT2, type CardT2Section } from '@/api/hr';
import { Button } from '@/components/ui/button';
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { MONEY_RE, SECTION_FIELDS, SECTION_TITLE } from '@/components/hr/cardT2Fields';

interface Props {
  employeeId: number;
  section: CardT2Section;
  /** Текущие значения секции из GET /card/t2 (могут быть все null). */
  values: Record<string, string | null> | undefined;
  open: boolean;
  onClose: () => void;
}

export function CardT2SectionDialog({ employeeId, section, values, open, onClose }: Props) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const fields = SECTION_FIELDS[section];
  const [form, setForm] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});

  // Перезаполняем форму при каждом открытии — иначе диалог показал бы данные
  // предыдущего сотрудника или устаревшие после чужой правки значения.
  useEffect(() => {
    if (!open) return;
    const next: Record<string, string> = {};
    for (const f of fields) next[f.name] = values?.[f.name] ?? '';
    setForm(next);
    setErrors({});
  }, [open, section, values, fields]);

  const mutation = useMutation({
    mutationFn: () => {
      const payload: Record<string, string | null> = {};
      for (const f of fields) {
        const raw = (form[f.name] ?? '').trim();
        payload[f.name] = raw === '' ? null : (f.kind === 'money' ? raw.replace(',', '.') : raw);
      }
      return updateCardT2(employeeId, section, payload);
    },
    onSuccess: (data: CardT2) => {
      // Кладём ответ в кэш сразу: он уже отфильтрован правами вызывающего.
      queryClient.setQueryData(['hr-card-t2', employeeId], data);
      queryClient.invalidateQueries({ queryKey: ['hr-card-t2', employeeId] });
      toast.success(t('hr.pages.employees.cardT2.saved', 'Сохранено'));
      onClose();
    },
    onError: (err: unknown) => {
      const status = (err as { response?: { status?: number } })?.response?.status;
      const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      if (status === 403) {
        toast.error(t('hr.pages.employees.cardT2.forbidden', 'Недостаточно прав для правки этого раздела'));
        return;
      }
      toast.error(typeof detail === 'string'
        ? detail
        : t('hr.pages.employees.cardT2.error', 'Не удалось сохранить'));
    },
  });

  const validate = (): boolean => {
    const next: Record<string, string> = {};
    for (const f of fields) {
      const raw = (form[f.name] ?? '').trim();
      if (raw === '') continue;
      if (f.kind === 'money' && !MONEY_RE.test(raw)) {
        next[f.name] = t('hr.pages.employees.cardT2.badNumber', 'Введите число, например 450000 или 450000.50');
      }
    }
    setErrors(next);
    return Object.keys(next).length === 0;
  };

  const title = SECTION_TITLE[section];

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="max-w-lg" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>{t(title.key, title.fallback)}</DialogTitle>
        </DialogHeader>

        <div className="grid gap-4">
          {fields.map((f) => (
            <div key={f.name} className="grid gap-1.5">
              <Label htmlFor={`t2-${f.name}`}>{t(f.labelKey, f.labelFallback)}</Label>
              <Input
                id={`t2-${f.name}`}
                type={f.kind === 'date' ? 'date' : 'text'}
                inputMode={f.kind === 'money' ? 'decimal' : undefined}
                value={form[f.name] ?? ''}
                onChange={(e) => setForm((prev) => ({ ...prev, [f.name]: e.target.value }))}
                aria-invalid={Boolean(errors[f.name])}
              />
              {errors[f.name] && (
                <p className="text-xs text-destructive">{errors[f.name]}</p>
              )}
            </div>
          ))}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={mutation.isPending}>
            {t('common.cancel', 'Отмена')}
          </Button>
          <Button
            onClick={() => { if (validate()) mutation.mutate(); }}
            disabled={mutation.isPending}
          >
            {mutation.isPending
              ? t('common.saving', 'Сохранение…')
              : t('common.save', 'Сохранить')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default CardT2SectionDialog;
