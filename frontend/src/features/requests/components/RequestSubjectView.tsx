/**
 * Заявка «Запросов» внутри карточки согласования.
 *
 * `apps.signoff` знает о предметном объекте ровно две вещи — тип и id, —
 * поэтому нарисовать документ может только его собственный раздел. Этот
 * компонент и есть та дверь: он зарегистрирован в `app/signoffSubjectViews`
 * под ключом `approvals.request` и получает id заявки.
 *
 * Показывает то, на основании чего принимают решение: код, заголовок и саму
 * форму значений — read-only, тем же `FormRenderer`, что рисует её
 * инициатору. Действий здесь нет: одобрить или вернуть заявку согласующий
 * может кнопками самой карточки процесса.
 *
 * Имя инициатора здесь НЕ резолвится, хотя соблазн есть: в заявке лежит один
 * `initiator_id`. Тянуть ради него справочник сотрудников (`GET
 * hr/v1/employees/`) нельзя — у согласующего прав на HR может не быть вовсе,
 * и тогда каждый показ карточки давал 403, react-query повторял его, а
 * перехватчик в `api/client.ts` на каждый 403 обновлял токен. Согласующий
 * получал пачку запросов и расшатанную сессию вместо одного имени. Имя ему и
 * не нужно отсюда: `apps.signoff` отдаёт `initiator_name` в самой карточке
 * процесса — резолвит на сервере, где права уже проверены.
 */

import { Link } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, ClipboardList, ExternalLink, FileText, Loader2, Paperclip } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Skeleton } from '@/components/ui/skeleton';
import { requestsApi, type StageStep } from '@/api/requests';
import { signoffApi } from '@/api/signoff';
import { reportApiError } from '@/lib/apiError';
import { FormRenderer } from '@/features/requests/components/FormRenderer';
import { mismatchIn } from '@/features/requests/requiredFields';
import { useInstance, useTemplate, useTemplateVersion } from '@/features/requests/hooks';
import type { FormSchema } from '@/features/requests/types';

interface Props {
  id: number;
  embedded?: boolean;
}

/**
 * Поля, которые заполняет согласующий на СВОЁМ шаге, — панелью над
 * документом, редактируемой только у того, чей шаг идёт.
 *
 * Кому и что можно, решает сервер (`stage-values/`): пусто — панели нет.
 * Поэтому здесь нет ни знания о маршруте, ни проверки «я ли закупщик» —
 * контракт SubjectView остаётся прежним (`{id, embedded}`), а права живут
 * там же, где и замок согласования.
 *
 * Рисуется тем же `FormRenderer`, что и вся форма, — на подсхеме из этих
 * полей с `filled_by` снятым: иначе рендер спрятал бы их как «не для
 * инициатора». Обязательные (без которых шаг не закроется) помечаются
 * звёздочкой из `required_keys` — сервер знает, чего ждёт именно этот этап.
 */
type Fillable = StageStep;

function useStageFillable(instanceId: number | null, enabled: boolean) {
  return useQuery({
    queryKey: ['requests', 'instances', instanceId, 'stage-values'],
    queryFn: () => requestsApi.instances.stageFillable(instanceId as number),
    enabled: instanceId != null && enabled,
  });
}

function StageFieldsPanel({ instanceId, schema, values, fillable }: {
  instanceId: number;
  schema: FormSchema;
  values: Record<string, unknown>;
  fillable: Fillable;
}) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [dirty, setDirty] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [comment, setComment] = useState('');
  const [error, setError] = useState('');

  // Значения из заявки — стартовые; пока человек правит, не перетираем.
  useEffect(() => {
    if (!dirty) setDraft(values);
  }, [values, dirty]);

  const keys = fillable.keys;

  const persist = () => {
    const picked: Record<string, unknown> = {};
    for (const key of fillable.keys) picked[key] = draft[key] ?? null;
    return requestsApi.instances.fillStageValues(instanceId, picked);
  };

  const save = useMutation({
    mutationFn: persist,
    onSuccess: () => {
      setDirty(false);
      toast.success('Сохранено в заявке');
      queryClient.invalidateQueries({ queryKey: ['requests', 'instances', instanceId] });
      queryClient.invalidateQueries({ queryKey: ['signoff'] });
    },
    onError: (err) => reportApiError(err, 'Не удалось сохранить'),
  });

  // «Сохранить и закрыть шаг» — то, чего человек ждёт от «Сохранить»:
  // заполнил — шаг сделан. Сохраняем поля и тут же шлём решение по задаче
  // этапа; гейты (требование к заявке, документ, пояснение) проверяет
  // движок и отвечает человеческим 409, если чего-то не хватает.
  // Порядок тот же, что у диалога решения: сначала файл (отдельный запрос,
  // вне транзакции процесса), потом поля, потом решение. Что не так —
  // движок скажет человеческим 409, панель его покажет.
  const closeStep = useMutation({
    mutationFn: async () => {
      const taskId = fillable.task_id as number;
      if (file) await signoffApi.attachDocument(taskId, file);
      if (dirty) await persist();
      return signoffApi.decide(taskId, { decision: 'approve', comment });
    },
    onSuccess: () => {
      setDirty(false);
      setFile(null);
      setComment('');
      toast.success('Шаг закрыт');
      // Решение сдвигает объект во всех доменах — перечитать всё, как и
      // после решения из «Действий» на карточке процесса.
      queryClient.invalidateQueries();
    },
    onError: (err) => reportApiError(err, 'Не удалось закрыть шаг'),
  });
  // Заменить документ — отдельным действием, а не только «заодно» при
  // закрытии шага: приложить не тот счёт легко, и чтобы это исправить,
  // человек не должен принимать решение по этапу.
  const attach = useMutation({
    mutationFn: (chosen: File) =>
      signoffApi.attachDocument(fillable.task_id as number, chosen),
    onSuccess: () => {
      setFile(null);
      toast.success('Документ заменён');
      queryClient.invalidateQueries({ queryKey: ['requests', 'instances', instanceId] });
      queryClient.invalidateQueries({ queryKey: ['signoff'] });
    },
    onError: (err) => reportApiError(err, 'Не удалось загрузить документ'),
  });

  const busy = save.isPending || closeStep.isPending || attach.isPending;

  const needsFile = fillable.requires_attachment && !file && !fillable.file_id;
  const needsComment = fillable.requires_comment && !comment.trim();
  const tryClose = () => {
    // Те же проверки, что на сервере, но до запроса: сказать «нужен PDF» до
    // загрузки дешевле для всех. Расхождение сумм считаем по ПОЛНЫМ
    // значениям заявки с наложенным черновиком: сравниваемое поле обычно
    // лежит в чужом блоке, заполненном на прошлом шаге.
    const mismatch = keys
      .map((key) => mismatchIn(schema, key, { ...values, ...draft }))
      .find(Boolean);
    if (mismatch) { setError(mismatch); return; }
    if (needsFile) { setError('Приложите счёт в PDF — без него шаг не закроется.'); return; }
    if (needsComment) { setError('Напишите пояснение — этап требует его.'); return; }
    setError('');
    closeStep.mutate();
  };

  const required = new Set(fillable.required_keys);
  const asks = [
    ...schema.fields.filter((field) => required.has(field.key)).map((field) => `«${field.label}»`),
    ...(fillable.requires_attachment ? ['счёт в PDF'] : []),
    ...(fillable.requires_comment ? ['пояснение'] : []),
  ];
  const subset: FormSchema = {
    ...schema,
    fields: schema.fields
      .filter((field) => keys.includes(field.key))
      .map((field) => ({ ...field, filled_by: 'initiator' as const,
                         required: required.has(field.key) })),
    display_conditions: [],
  };

  return (
    <div className="rounded-lg border border-primary/30 bg-primary/5 p-4 space-y-3">
      <div className="flex items-start gap-2">
        <ClipboardList className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
        <div>
          <p className="text-sm font-medium">
            Ваш шаг{fillable.stage_name ? `: ${fillable.stage_name}` : ''}
          </p>
          <p className="text-xs text-muted-foreground">
            {asks.length > 0 ? `Чтобы закрыть шаг, нужно: ${asks.join(', ')}. ` : ''}
            «Сохранить и закрыть шаг» — и заявка уйдёт дальше; «Сохранить» —
            чтобы вернуться позже.
          </p>
        </div>
      </div>
      {keys.length > 0 && (
        <FormRenderer
          schema={subset}
          values={draft}
          onChange={(next) => { setDraft(next); setDirty(true); }}
        />
      )}

      {/* Документ и пояснение — то, чего этап ждёт от РЕШЕНИЯ, а не от
          заявки; уходят на задачу signoff, как из диалога «Действия». */}
      {fillable.requires_attachment && (
        <div className="space-y-1.5">
          <Label htmlFor="step-document">Счёт (PDF)</Label>

          {/* Что приложено СЕЙЧАС — ссылкой и по имени: «документ приложен»
              без имени не даёт заметить, что ушёл не тот счёт. */}
          {fillable.file_id && !file && (
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border bg-muted/30 p-2">
              <span className="flex min-w-0 items-center gap-1.5 text-sm">
                <Paperclip className="h-4 w-4 shrink-0 opacity-70" />
                {fillable.file_url ? (
                  <a
                    href={fillable.file_url}
                    target="_blank"
                    rel="noreferrer"
                    className="truncate text-primary hover:underline underline-offset-2"
                  >
                    {fillable.file_name || 'Приложенный документ'}
                  </a>
                ) : (
                  <span className="truncate">{fillable.file_name || 'Приложенный документ'}</span>
                )}
              </span>
              <span className="text-xs text-muted-foreground">
                Откройте и проверьте — заменить можно до закрытия шага.
              </span>
            </div>
          )}

          <input
            id="step-document"
            type="file"
            accept="application/pdf"
            disabled={busy}
            onChange={(event) => {
              const chosen = event.target.files?.[0] ?? null;
              if (chosen && chosen.type !== 'application/pdf') {
                setError('Документ принимается только в PDF.');
                setFile(null);
                return;
              }
              setError('');
              setFile(chosen);
            }}
            className="block w-full text-sm text-muted-foreground
                       file:mr-3 file:rounded-md file:border-0
                       file:bg-secondary file:px-3 file:py-1.5
                       file:text-sm file:font-medium file:text-secondary-foreground"
          />
          {file && (
            <div className="flex flex-wrap items-center gap-2">
              <p className="flex min-w-0 items-center gap-1.5 text-sm text-muted-foreground">
                <FileText className="h-4 w-4 shrink-0" />
                <span className="truncate">{file.name}</span>
              </p>
              {/* Загрузить сразу, не закрывая шаг: ошиблись файлом —
                  исправляют файл, а не принимают решение по этапу. */}
              {fillable.file_id && (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={busy}
                  onClick={() => attach.mutate(file)}
                >
                  {attach.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  Заменить документ
                </Button>
              )}
            </div>
          )}
        </div>
      )}
      {fillable.requires_comment && (
        <div className="space-y-1.5">
          <Label htmlFor="step-comment">Пояснение</Label>
          <Textarea
            id="step-comment"
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            maxLength={2000}
            rows={3}
            disabled={busy}
          />
        </div>
      )}
      {error && <p className="text-sm text-destructive">{error}</p>}

      <div className="flex flex-wrap justify-end gap-2">
        <Button size="sm" variant="outline" onClick={() => save.mutate()} disabled={busy || !dirty}>
          {save.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
          Сохранить
        </Button>
        {fillable.task_id !== null && (
          <Button size="sm" onClick={tryClose} disabled={busy}>
            {closeStep.isPending
              ? <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              : <Check className="mr-2 h-4 w-4" />}
            Сохранить и закрыть шаг
          </Button>
        )}
      </div>
    </div>
  );
}

const RequestSubjectView = ({ id }: Props) => {
  const instance = useInstance(Number.isFinite(id) ? id : null);
  const template = useTemplate(instance.data?.template_id ?? null);
  const version = useTemplateVersion(
    instance.data?.template_id ?? null,
    instance.data?.template_version_id ?? null,
  );
  // Что этот человек может заполнить сейчас — спрашиваем только у заявки на
  // согласовании: у черновика и закрытой заявки рабочих шагов нет.
  const fillable = useStageFillable(instance.data?.id ?? null,
                                    instance.data?.status === 'pending');
  const editingKeys = fillable.data?.keys ?? [];
  // Рабочий шаг — когда этап ждёт от человека блок заявки или документ.
  // Голое утверждение (CFO) панели не получает: там решение с отказом и
  // доработкой, это «Действия» карточки процесса.
  const isWorkStep = Boolean(fillable.data?.task_id)
    && (editingKeys.length > 0 || Boolean(fillable.data?.requires_attachment));
  if (instance.isLoading) return <Skeleton className="h-40" />;
  if (instance.isError || !instance.data) {
    return <p className="text-sm text-muted-foreground">Заявка не найдена.</p>;
  }

  const data = instance.data;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-medium break-words">{data.title || data.code}</p>
          <p className="text-xs text-muted-foreground">
            <span className="font-mono">{data.code}</span>
            {template.data && <> · {template.data.name}</>}
          </p>
        </div>
        <Link
          to={`/requests/${data.id}`}
          className="inline-flex items-center gap-1 text-sm text-primary hover:underline underline-offset-2"
        >
          <ExternalLink className="h-3.5 w-3.5" />
          Открыть заявку
        </Link>
      </div>

      {version.isLoading ? (
        <Skeleton className="h-24" />
      ) : version.data ? (
        <>
          {isWorkStep && fillable.data && (
            <StageFieldsPanel
              instanceId={data.id}
              schema={version.data.schema_json}
              values={data.form_values_json as Record<string, unknown>}
              fillable={fillable.data}
            />
          )}
          {/* Поля, которые сейчас редактируются в панели выше, из формы
              чтения убраны: второй раз показывать то же поле незачем, а
              одинаковые id у двух инпутов ломают подписи. У всех остальных
              (CFO, инициатор) поля закупщика видны здесь, с значениями. */}
          <FormRenderer
            schema={{
              ...version.data.schema_json,
              fields: version.data.schema_json.fields
                .filter((field) => !editingKeys.includes(field.key)),
            }}
            values={data.form_values_json as Record<string, unknown>}
            onChange={() => undefined}
            readOnly
          />
        </>
      ) : null}
    </div>
  );
};

export default RequestSubjectView;
