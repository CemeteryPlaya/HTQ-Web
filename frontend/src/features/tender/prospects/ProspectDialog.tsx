/**
 * Создание и правка потенциального поставщика: наименование, e-mail (на
 * него уйдёт ссылка тендера), рег. номер, код страны. Правка несёт
 * `version`; 409 `E-CON-01` — сообщение и «Обновить».
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

import { ConflictAlert } from '../core/ConflictAlert';
import { isConflict } from '../core/conflict';
import { fieldErrorsOf, reportFormError } from '../core/fieldErrors';
import { prospectsApi, type Prospect, type ProspectInput } from './api';

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const COUNTRY = /^[A-Z]{2}$/;

interface Props {
  /** `null` — новый поставщик. */
  prospect: Prospect | null;
  onClose: () => void;
  onSaved: () => void;
}

export function ProspectDialog({ prospect, onClose, onSaved }: Props) {
  const { t } = useTranslation();
  const [form, setForm] = useState<ProspectInput>(() => ({
    name: prospect?.name ?? '',
    email: prospect?.email ?? '',
    reg_number: prospect?.reg_number ?? '',
    country_code: prospect?.country_code ?? 'KZ',
  }));
  const [showErrors, setShowErrors] = useState(false);
  const [pending, setPending] = useState(false);
  const [conflict, setConflict] = useState(false);
  // Отказ сервера по полям (e-mail занят, неверный код страны, …).
  const [serverErrors, setServerErrors] = useState<Record<string, string>>({});

  const body: ProspectInput = {
    name: form.name.trim(),
    email: form.email.trim(),
    reg_number: form.reg_number.trim(),
    country_code: form.country_code.trim().toUpperCase(),
  };
  const errors: Record<string, string> = {};
  if (body.name.length < 2) errors.name = t('tender.prospects.nameShort', 'Наименование — от 2 символов');
  if (!EMAIL.test(body.email)) errors.email = t('tender.prospects.emailInvalid', 'Укажите e-mail вида name@example.kz');
  if (!COUNTRY.test(body.country_code)) {
    errors.country_code = t('tender.prospects.countryInvalid', 'Код страны — две латинские буквы, например KZ');
  }

  const save = async () => {
    setShowErrors(true);
    if (Object.keys(errors).length > 0) return;
    setPending(true);
    setServerErrors({});
    try {
      if (prospect) await prospectsApi.save(prospect.id, { ...body, version: prospect.version });
      else await prospectsApi.create(body);
      onSaved();
    } catch (failure) {
      if (isConflict(failure)) setConflict(true);
      setServerErrors(fieldErrorsOf(failure, t('tender.common.invalidFormat', 'Неверный формат значения')));
      reportFormError(
        failure,
        t('tender.prospects.saveFailed', 'Не удалось сохранить поставщика'),
        t('tender.common.invalidFormatToast', 'Сервер не принял формат некоторых полей — проверьте выделенные поля.'),
      );
    } finally {
      setPending(false);
    }
  };

  const field = (key: keyof ProspectInput, label: string, extra: object = {}) => {
    const problem = serverErrors[key] ?? (showErrors ? errors[key] : undefined);
    return (
      <div className="space-y-1.5">
        <Label htmlFor={`tender-prospect-${key}`}>{label}</Label>
        <Input
          id={`tender-prospect-${key}`} value={form[key]} {...extra}
          aria-invalid={problem ? true : undefined}
          onChange={(event) => setForm({ ...form, [key]: event.target.value })}
        />
        {problem && <p className="text-xs text-destructive">{problem}</p>}
      </div>
    );
  };

  return (
    <Dialog open onOpenChange={(open) => { if (!open && !pending) onClose(); }}>
      <DialogContent aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>
            {prospect
              ? t('tender.prospects.editTitle', 'Потенциальный поставщик')
              : t('tender.prospects.createTitle', 'Новый потенциальный поставщик')}
          </DialogTitle>
        </DialogHeader>
        {conflict && (
          <ConflictAlert
            message={t('tender.prospects.conflict',
              'Карточку поставщика уже изменили — обновите список и повторите правку.')}
            onReload={onSaved}
          />
        )}
        <div className="grid gap-3">
          {field('name', t('tender.prospects.name', 'Наименование'), { maxLength: 255 })}
          {field('email', t('tender.prospects.email', 'E-mail'), { type: 'email', maxLength: 254 })}
          <div className="grid gap-3 sm:grid-cols-2">
            {field('reg_number', t('tender.prospects.regNumber', 'Рег. номер (БИН/ИИН)'), { maxLength: 32 })}
            {field('country_code', t('tender.prospects.country', 'Страна (код)'), { maxLength: 2 })}
          </div>
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" disabled={pending} onClick={onClose}>
            {t('tender.common.cancel', 'Отмена')}
          </Button>
          <Button type="button" disabled={pending} onClick={() => { void save(); }}>
            {pending && <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />}
            {t('tender.prospects.save', 'Сохранить')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
