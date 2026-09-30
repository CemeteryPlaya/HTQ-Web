/**
 * Вкладка «Параметры модуля» экрана «Настройки» (ТЗ §05 п.10
 * «Администрирование»): параметры из серверного реестра
 * (`GET /api/bpp/v1/settings`) с правкой по месту. Первый — порог метки
 * «Проверенный» у контрагента (D-20).
 *
 * Правит держатель `bpp.settings` `edit` (АДМ); без права значение только
 * показывается. Проверка «целое от min до max» идёт до запроса тем же
 * правилом, что на сервере; отказ сервера (422 `E-VAL-01`) показывается у
 * поля. Смена пишется в журнал модуля; умолчание — пока параметр не меняли.
 */
import { useState, type FormEvent } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { reportApiError } from '@/lib/apiError';

import { errorFields } from '../counterparties/errors';
import { useIdempotentAction } from '../core/useIdempotentAction';

import { MODULE_PARAMS_KEY, moduleParamsApi, type ModuleParam } from './api';

/** Целое в границах параметра; иначе `null` — форма покажет правило. */
function parseValue(param: ModuleParam, raw: string): number | null {
  const text = raw.trim();
  if (!/^-?\d+$/.test(text)) return null;
  const value = Number(text);
  if (param.min !== null && value < param.min) return null;
  if (param.max !== null && value > param.max) return null;
  return value;
}

function ParamRow({ param, canEdit }: { param: ModuleParam; canEdit: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState(String(param.value));
  const [error, setError] = useState<string | null>(null);
  const inputId = `bpp-param-${param.key}`;
  const rule = t('bpp.moduleParams.rule', 'Целое число от {{min}} до {{max}}', {
    min: param.min, max: param.max,
  });

  const parsed = parseValue(param, draft);
  const save = useIdempotentAction((key) => moduleParamsApi.update(param.key, key, parsed ?? 0));
  const dirty = draft.trim() !== String(param.value);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (parsed === null) {
      setError(rule);
      return;
    }
    save.run().then(
      (saved) => {
        setDraft(String(saved.value));
        queryClient.setQueryData<ModuleParam[]>(MODULE_PARAMS_KEY, (current) =>
          current?.map((item) => (item.key === saved.key ? saved : item)));
        toast.success(t('bpp.moduleParams.saved', 'Параметр сохранён'));
      },
      (failure: unknown) => {
        const field = errorFields(failure).find((item) => item.field === 'value');
        if (field) setError(field.message);
        else reportApiError(failure, t('bpp.moduleParams.saveFailed', 'Не удалось сохранить параметр'));
      },
    );
  };

  const isDefault = param.value === param.default;
  const hint = (
    <p className="text-xs text-muted-foreground">
      {isDefault
        ? t('bpp.moduleParams.isDefault', 'Действует значение по умолчанию.')
        : t('bpp.moduleParams.default', 'По умолчанию — {{value}}.', { value: param.default })}
    </p>
  );

  return (
    <li className="space-y-2 rounded-md border p-4">
      <form
        aria-label={param.label}
        onSubmit={submit}
        // Проверку границ ведёт форма сама: браузерная всплывашка у поля
        // говорила бы другим текстом, чем сервер (E-VAL-01).
        noValidate
        className="flex flex-wrap items-end gap-3"
      >
        <div className="min-w-0 flex-1 space-y-1.5">
          <Label htmlFor={inputId}>{param.label}</Label>
          {param.help && <p className="text-sm text-muted-foreground">{param.help}</p>}
        </div>
        {canEdit ? (
          <div className="flex items-start gap-2">
            <Input
              id={inputId}
              type="number"
              inputMode="numeric"
              step={1}
              min={param.min ?? undefined}
              max={param.max ?? undefined}
              value={draft}
              onChange={(event) => {
                setDraft(event.target.value);
                setError(null);
              }}
              className="w-28"
              aria-invalid={error ? true : undefined}
              aria-describedby={error ? `${inputId}-error` : undefined}
              disabled={save.pending}
            />
            <Button type="submit" disabled={!dirty || save.pending}>
              {t('bpp.moduleParams.save', 'Сохранить')}
            </Button>
          </div>
        ) : (
          <output id={inputId} className="text-lg font-semibold tabular-nums">
            {param.value}
          </output>
        )}
      </form>
      {error && (
        <p id={`${inputId}-error`} className="text-xs text-destructive">{error}</p>
      )}
      {hint}
    </li>
  );
}

interface Props {
  canEdit: boolean;
}

export function ModuleParamsTab({ canEdit }: Props) {
  const { t } = useTranslation();
  const params = useQuery({ queryKey: MODULE_PARAMS_KEY, queryFn: moduleParamsApi.list });

  if (params.isLoading) return <Skeleton className="h-24 w-full" />;
  if (params.isError) {
    return (
      <p className="text-sm text-destructive">
        {t('bpp.moduleParams.loadFailed', 'Не удалось загрузить параметры модуля')}
      </p>
    );
  }
  const rows = params.data ?? [];
  return (
    <div className="space-y-3">
      {!canEdit && (
        <p className="text-sm text-muted-foreground">
          {t('bpp.moduleParams.readOnly', 'Параметры меняет администратор модуля.')}
        </p>
      )}
      {rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {t('bpp.moduleParams.empty', 'Параметров для настройки нет.')}
        </p>
      ) : (
        <ul className="space-y-3">
          {rows.map((param) => (
            // Ключ со временем правки: пришло новое значение (другой АДМ,
            // перечитывание) — поле берёт его, а не держит старое.
            <ParamRow key={`${param.key}:${param.updated_at ?? ''}`} param={param} canEdit={canEdit} />
          ))}
        </ul>
      )}
    </div>
  );
}
