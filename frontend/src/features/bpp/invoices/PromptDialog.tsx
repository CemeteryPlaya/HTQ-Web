/**
 * Диалог с полями для действий счёта, которым мало «подтвердить с
 * комментарием» (`DocumentActionButton.confirm`): решение ФД с плановой
 * датой оплаты, отметка оплаты БУХ, запрос закрывающих документов, массовые
 * решения реестра.
 *
 * `ask(spec)` открывает диалог и ждёт: `true` — `spec.submit` прошёл,
 * `false` — человек закрыл диалог. Ошибка `submit` показывается тостом, а
 * диалог остаётся открытым с введёнными значениями — исправить и повторить.
 * Ключ `Idempotency-Key` держит вызывающий на всё время `ask`: сервер не
 * запоминает ответы-отказы (`htqweb/idempotency.py::remember` — только
 * успешные), поэтому повтор после исправления тем же ключом — новая попытка,
 * а повтор после обрыва сети — тот же запрос.
 */
import { useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { DateInput } from '@/components/ui/date-input';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { reportApiError } from '@/lib/apiError';
import { cn } from '@/lib/utils';

import { formatMoney, parseMoneyInput } from '../format';

export type PromptValue = string | boolean | File | null;
export type PromptValues = Record<string, PromptValue>;

export type PromptField =
  | { key: string; kind: 'date'; label: string; required?: boolean; hint?: string }
  | { key: string; kind: 'text'; label: string; required?: boolean; maxLength?: number }
  | { key: string; kind: 'money'; label: string; required?: boolean; hint?: string }
  | { key: string; kind: 'comment'; label: string; min: number }
  | { key: string; kind: 'check'; label: string }
  /** Файл: `accept` — подсказка окну выбора, `check` — проверка до запроса
   * (формат и размер, как у справочника «Типы файлов»; отказ объясняет сам). */
  | { key: string; kind: 'file'; label: string; accept?: string; check?: (file: File) => boolean };

export interface PromptSpec {
  title: string;
  description?: string;
  submitLabel: string;
  destructive?: boolean;
  fields: PromptField[];
  initial?: PromptValues;
  /** Проверка значений целиком: текст ошибки — кнопка закрыта. */
  validate?: (values: PromptValues) => string | null;
  submit: (values: PromptValues) => Promise<unknown>;
}

interface Open {
  spec: PromptSpec;
  resolve: (done: boolean) => void;
}

const text = (values: PromptValues, key: string) => {
  const value = values[key];
  return typeof value === 'string' ? value : '';
};

/** Ошибка поля или `null`; пустое необязательное поле — не ошибка. */
function fieldProblem(field: PromptField, values: PromptValues): string | null {
  const value = text(values, field.key).trim();
  switch (field.kind) {
    case 'comment':
      return value.length < field.min ? `Минимум ${field.min} символов, сейчас ${value.length}` : null;
    case 'money':
      if (!value) return field.required ? 'Укажите сумму' : null;
      return parseMoneyInput(value) === null ? 'Введите сумму в формате 1 250 000,00' : null;
    case 'date':
    case 'text':
      return field.required && !value ? 'Обязательное поле' : null;
    case 'file':
      return values[field.key] instanceof File ? null : 'Выберите файл';
    default:
      return null;
  }
}

export function usePrompt() {
  const { t } = useTranslation();
  const [open, setOpen] = useState<Open | null>(null);
  const [values, setValues] = useState<PromptValues>({});
  const [pending, setPending] = useState(false);

  const ask = useCallback((spec: PromptSpec) => new Promise<boolean>((resolve) => {
    const initial: PromptValues = {};
    for (const field of spec.fields) {
      initial[field.key] = field.kind === 'check' ? false : field.kind === 'file' ? null : '';
    }
    setValues({ ...initial, ...spec.initial });
    setOpen({ spec, resolve });
  }), []);

  const close = (done: boolean) => {
    open?.resolve(done);
    setOpen(null);
  };

  const spec = open?.spec;
  const problems = spec
    ? spec.fields.map((field) => [field.key, fieldProblem(field, values)] as const)
    : [];
  const formProblem = spec?.validate?.(values) ?? null;
  const blocked = problems.some(([, problem]) => problem !== null) || formProblem !== null;
  // Пустое обязательное поле не краснеет, пока в него ничего не ввели.
  const shownProblem = (field: PromptField) => {
    const problem = problems.find(([key]) => key === field.key)?.[1] ?? null;
    return text(values, field.key) ? problem : null;
  };

  const submit = async () => {
    if (!spec || blocked || pending) return;
    setPending(true);
    try {
      await spec.submit(values);
      close(true);
    } catch (error) {
      reportApiError(error, t('bpp.document.actionFailed', 'Не удалось выполнить действие'));
    } finally {
      setPending(false);
    }
  };

  const set = (key: string, value: PromptValue) =>
    setValues((current) => ({ ...current, [key]: value }));

  const dialog = (
    <Dialog open={open !== null} onOpenChange={(next) => { if (!next && !pending) close(false); }}>
      {spec && (
        <DialogContent {...(spec.description ? {} : { 'aria-describedby': undefined })}>
          <DialogHeader>
            <DialogTitle>{spec.title}</DialogTitle>
            {spec.description && <DialogDescription>{spec.description}</DialogDescription>}
          </DialogHeader>
          <div className="space-y-3">
            {spec.fields.map((field) => {
              const id = `bpp-prompt-${field.key}`;
              const problem = shownProblem(field);
              if (field.kind === 'check') {
                return (
                  <label key={field.key} className="flex items-center gap-2 text-sm">
                    <Checkbox checked={values[field.key] === true} disabled={pending}
                      onCheckedChange={(checked) => set(field.key, checked === true)} />
                    {field.label}
                  </label>
                );
              }
              return (
                <div key={field.key} className="space-y-1.5">
                  <Label htmlFor={id}>{field.label}</Label>
                  {field.kind === 'date' && (
                    <DateInput id={id} value={text(values, field.key)} disabled={pending}
                      onChange={(value) => set(field.key, value)} />
                  )}
                  {field.kind === 'text' && (
                    <Input id={id} value={text(values, field.key)} disabled={pending}
                      maxLength={field.maxLength}
                      onChange={(event) => set(field.key, event.target.value)} />
                  )}
                  {field.kind === 'money' && (
                    <Input id={id} className="text-right" inputMode="decimal" disabled={pending}
                      value={text(values, field.key)}
                      onChange={(event) => set(field.key, event.target.value)}
                      onBlur={() => {
                        const parsed = parseMoneyInput(text(values, field.key));
                        if (parsed !== null) set(field.key, formatMoney(parsed));
                      }} />
                  )}
                  {field.kind === 'file' && (
                    <Input id={id} type="file" accept={field.accept} disabled={pending}
                      onChange={(event) => {
                        const file = event.target.files?.[0] ?? null;
                        if (file && field.check && !field.check(file)) {
                          event.target.value = '';
                          set(field.key, null);
                          return;
                        }
                        set(field.key, file);
                      }} />
                  )}
                  {field.kind === 'comment' && (
                    <Textarea id={id} rows={4} value={text(values, field.key)} disabled={pending}
                      maxLength={1000}
                      onChange={(event) => set(field.key, event.target.value)} />
                  )}
                  {field.kind === 'comment' ? (
                    <p aria-live="polite" className={cn('text-xs',
                      problem ? 'text-destructive' : 'text-muted-foreground')}>
                      {t('bpp.document.commentCounter', 'Минимум {{min}} символов, сейчас {{count}}', {
                        min: field.min, count: text(values, field.key).trim().length,
                      })}
                    </p>
                  ) : problem ? (
                    <p className="text-xs text-destructive">{problem}</p>
                  ) : 'hint' in field && field.hint ? (
                    <p className="text-xs text-muted-foreground">{field.hint}</p>
                  ) : null}
                </div>
              );
            })}
            {formProblem && <p role="alert" className="text-sm text-destructive">{formProblem}</p>}
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" disabled={pending} onClick={() => close(false)}>
              {t('bpp.document.cancel', 'Отмена')}
            </Button>
            <Button type="button" variant={spec.destructive ? 'destructive' : 'default'}
              disabled={blocked || pending} onClick={submit}>
              {pending && <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />}
              {spec.submitLabel}
            </Button>
          </DialogFooter>
        </DialogContent>
      )}
    </Dialog>
  );

  return { ask, dialog };
}
