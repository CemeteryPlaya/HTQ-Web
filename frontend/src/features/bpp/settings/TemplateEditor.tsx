/**
 * Редактор шаблона выписки (ТЗ §18 «Банковские счета организации и шаблоны
 * выписок», §11.2; A3.1): как читать файл банк-клиента.
 *
 * - сопоставление «поле выписки ↔ текст заголовка колонки»: колонки сервер
 *   ищет по заголовку в первых 30 строках файла, порядок колонок и лишние
 *   колонки не мешают (`services/bank/templates.py`);
 * - недостающие обязательные колонки видны сразу, до «Сохранить»
 *   (`templateFields.missingRequired`, то же правило, что на сервере);
 * - выписке 1С колонки не нужны — её поля задаёт стандарт формата;
 * - «Проверить на образце» — первые 20 строк образца и ошибки строк по
 *   СОХРАНЁННОМУ шаблону (сервер ничего не сохраняет); с несохранёнными
 *   правками проверка недоступна, иначе человек смотрел бы на результат
 *   старого шаблона и думал, что он новый;
 * - после сохранения форма берёт значения из ответа сервера: он приводит
 *   кодировку и название к своему виду, и без этого сохранённый шаблон
 *   выглядел бы «изменённым» (а проверка образца — недоступной).
 *
 * Править вправе держатель `bpp.settings` `edit` (АДМ); без права форма
 * только для чтения, но образец проверить можно — это чтение.
 */
import { useMemo, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { FileSearch, Loader2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { reportApiError } from '@/lib/apiError';

import { errorFields } from '../counterparties/errors';
import { useIdempotentAction } from '../core/useIdempotentAction';
import { useUnsavedChangesGuard } from '../core/useUnsavedChangesGuard';
import { formatDate, formatMoney } from '../format';

import {
  bankSettingsApi, type AmountMode, type StatementFormat, type StatementTemplate,
  type TemplateInput, type TemplatePreview,
} from './api';
import {
  FORMAT_ACCEPT, FORMAT_LABELS, missingRequired, requiredFields, TEMPLATE_FIELDS,
  unusedAmountFields,
} from './templateFields';

interface Props {
  /** `null` — новый шаблон. */
  template: StatementTemplate | null;
  canEdit: boolean;
  onSaved: (template: StatementTemplate) => void;
  onClose: () => void;
}

const EMPTY: TemplateInput = {
  name: '',
  format: 'xlsx',
  encoding: '',
  delimiter: ';',
  date_format: 'ДД.ММ.ГГГГ',
  columns: {},
  amount_mode: 'signed',
};

const fromTemplate = (template: StatementTemplate | null): TemplateInput => (template
  ? {
    name: template.name,
    format: template.format,
    encoding: template.encoding,
    delimiter: template.delimiter,
    date_format: template.date_format,
    columns: { ...template.columns },
    amount_mode: template.amount_mode,
  }
  : EMPTY);

/** Колонки к отправке: без пустых и без полей суммы чужого режима; у 1С — никаких. */
function cleanColumns(values: TemplateInput): Record<string, string> {
  if (values.format === 'onec') return {};
  const unused = unusedAmountFields(values.amount_mode);
  return Object.fromEntries(
    Object.entries(values.columns)
      .map(([field, header]) => [field, header.trim()] as const)
      .filter(([field, header]) => header && !unused.includes(field)),
  );
}

const sameInput = (a: TemplateInput, b: TemplateInput) =>
  JSON.stringify({ ...a, columns: cleanColumns(a) }) === JSON.stringify({ ...b, columns: cleanColumns(b) });

type Errors = Partial<Record<'name' | 'columns' | 'encoding' | 'delimiter' | 'date_format' | 'form', string>>;

/** Поля, у которых форма показывает отказ сервера; прочие — общей строкой. */
const FIELD_ERRORS = ['name', 'columns', 'encoding', 'delimiter', 'date_format'];

class TemplateInvalid extends Error {}

function PreviewResult({ preview }: { preview: TemplatePreview }) {
  const { t } = useTranslation();
  const notFound = preview.columns.filter((column) => column.index === null);
  return (
    <div className="space-y-3 text-sm">
      <p className="text-muted-foreground">
        {t('bpp.bankSettings.previewHeaderRow', 'Строка заголовка в файле: {{row}}', {
          row: preview.header_row,
        })}
      </p>
      {notFound.length > 0 && (
        <p className="text-amber-700 dark:text-amber-300">
          {t('bpp.bankSettings.previewNotFound', 'Не найдены необязательные колонки: {{names}}', {
            names: notFound.map((column) => `«${column.header}»`).join(', '),
          })}
        </p>
      )}
      {preview.errors.length > 0 && (
        <div role="alert" className="rounded-lg border border-destructive/40 p-3">
          <p className="mb-1 font-medium text-destructive">
            {t('bpp.bankSettings.previewErrors', 'Строки с ошибками')}
          </p>
          <ul className="list-disc space-y-0.5 pl-5">
            {preview.errors.map((error) => <li key={error}>{error}</li>)}
          </ul>
        </div>
      )}
      {preview.rows.length === 0 ? (
        <p className="text-muted-foreground">
          {t('bpp.bankSettings.previewEmpty', 'В начале файла нет ни одной распознанной строки.')}
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t('bpp.bankSettings.previewRow', 'Строка')}</TableHead>
                <TableHead>{t('bpp.bankSettings.fields.date', 'Дата')}</TableHead>
                <TableHead>{t('bpp.bankSettings.fields.doc_number', 'Номер документа')}</TableHead>
                <TableHead>{t('bpp.bankSettings.previewDirection', 'Операция')}</TableHead>
                <TableHead className="text-right">{t('bpp.bankSettings.fields.amount', 'Сумма')}</TableHead>
                <TableHead>{t('bpp.bankSettings.fields.recipient_name', 'Получатель')}</TableHead>
                <TableHead>{t('bpp.bankSettings.fields.purpose', 'Назначение платежа')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {preview.rows.map((row) => (
                <TableRow key={row.row_no}>
                  <TableCell className="tabular-nums">{row.row_no}</TableCell>
                  <TableCell>{formatDate(row.date)}</TableCell>
                  <TableCell>{row.doc_number}</TableCell>
                  <TableCell>
                    {row.direction === 'debit'
                      ? t('bpp.bankSettings.debit', 'Списание')
                      : t('bpp.bankSettings.credit', 'Поступление')}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">
                    {formatMoney(row.amount, row.currency || undefined)}
                  </TableCell>
                  <TableCell>{row.recipient_name || '—'}</TableCell>
                  <TableCell className="max-w-80 truncate" title={row.purpose}>
                    {row.purpose || '—'}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}

export function TemplateEditor({ template, canEdit, onSaved, onClose }: Props) {
  const { t } = useTranslation();
  const initial = useMemo(() => fromTemplate(template), [template]);
  const [values, setValues] = useState<TemplateInput>(initial);
  const [errors, setErrors] = useState<Errors>({});
  const [sample, setSample] = useState<File | null>(null);
  const [preview, setPreview] = useState<TemplatePreview | null>(null);
  const [previewing, setPreviewing] = useState(false);

  const dirty = canEdit && !sameInput(values, initial);
  const missing = missingRequired(values.format, values.amount_mode, values.columns);
  const required = requiredFields(values.amount_mode);
  const unused = unusedAmountFields(values.amount_mode);

  const save = useIdempotentAction((key) => {
    const body = { ...values, name: values.name.trim(), columns: cleanColumns(values) };
    return template
      ? bankSettingsApi.updateTemplate(template.id, key, { ...body, version: template.version })
      : bankSettingsApi.createTemplate(key, body);
  });

  const set = <K extends keyof TemplateInput>(key: K, value: TemplateInput[K]) => {
    setValues((current) => ({ ...current, [key]: value }));
    setErrors((current) => ({ ...current, [key]: undefined, form: undefined }));
  };
  const setColumn = (field: string, header: string) => {
    setValues((current) => ({ ...current, columns: { ...current.columns, [field]: header } }));
    setErrors((current) => ({ ...current, columns: undefined }));
  };

  /** Проверка и сохранение; отказ — исключение (его ждёт и диалог ухода). */
  const persist = async (): Promise<StatementTemplate> => {
    const found: Errors = {};
    if (!values.name.trim()) found.name = t('bpp.bankSettings.nameRequired', 'Укажите название шаблона');
    if (missing.length > 0) {
      found.columns = t('bpp.bankSettings.columnsMissing', 'Не заполнены обязательные колонки: {{names}}', {
        names: missing.map((field) => `«${t(field.labelKey, field.label)}»`).join(', '),
      });
    }
    if (Object.keys(found).length > 0) {
      setErrors(found);
      throw new TemplateInvalid(found.name ?? found.columns);
    }
    try {
      const saved = await save.run();
      // Родитель передаст `saved` новым `template`, и `initial` станет им же.
      setValues(fromTemplate(saved));
      onSaved(saved);
      return saved;
    } catch (error) {
      const fields = errorFields(error);
      if (fields.length > 0) {
        setErrors(Object.fromEntries(fields.map((item) => [
          FIELD_ERRORS.includes(item.field) ? item.field : 'form', item.message,
        ])));
      }
      throw error;
    }
  };

  const guard = useUnsavedChangesGuard({ dirty, onSaveDraft: persist });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    persist().catch((error: unknown) => {
      if (error instanceof TemplateInvalid || errorFields(error).length > 0) return;
      reportApiError(error, t('bpp.bankSettings.saveFailed', 'Не удалось сохранить шаблон'));
    });
  };

  const runPreview = async () => {
    if (!template || !sample) return;
    setPreviewing(true);
    setPreview(null);
    try {
      setPreview(await bankSettingsApi.preview(template.id, sample));
    } catch (error) {
      reportApiError(error, t('bpp.bankSettings.previewFailed', 'Не удалось проверить образец'));
    } finally {
      setPreviewing(false);
    }
  };

  const readOnly = !canEdit || save.pending;
  const isOnec = values.format === 'onec';
  const previewBlocked = !template
    ? t('bpp.bankSettings.previewNeedsSave', 'Сохраните шаблон, чтобы проверить образец.')
    : template.format === 'onec' || isOnec
      ? t('bpp.bankSettings.previewOnec', 'Предпросмотр доступен для шаблонов Excel и CSV: выписка 1С разбирается по стандарту формата.')
      : dirty
        ? t('bpp.bankSettings.previewDirty', 'Есть несохранённые изменения — сохраните шаблон, чтобы проверить образец по ним.')
        : null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">
          {template
            ? t('bpp.bankSettings.editTemplate', 'Шаблон «{{name}}»', { name: template.name })
            : t('bpp.bankSettings.newTemplate', 'Новый шаблон выписки')}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        <form onSubmit={submit} noValidate className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="tpl-name">{t('bpp.bankSettings.name', 'Название')}</Label>
              <Input
                id="tpl-name"
                value={values.name}
                onChange={(event) => set('name', event.target.value)}
                disabled={readOnly}
                aria-invalid={errors.name ? true : undefined}
              />
              {errors.name && <p className="text-xs text-destructive">{errors.name}</p>}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="tpl-format">{t('bpp.bankSettings.format', 'Формат файла')}</Label>
              <Select
                value={values.format}
                onValueChange={(value) => set('format', value as StatementFormat)}
                disabled={readOnly}
              >
                <SelectTrigger id="tpl-format"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {(Object.keys(FORMAT_LABELS) as StatementFormat[]).map((format) => (
                    <SelectItem key={format} value={format}>
                      {t(FORMAT_LABELS[format][0], FORMAT_LABELS[format][1])}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="tpl-encoding">{t('bpp.bankSettings.encoding', 'Кодировка')}</Label>
              <Input
                id="tpl-encoding"
                value={values.encoding}
                placeholder={values.format === 'xlsx' ? 'utf-8' : 'cp1251'}
                onChange={(event) => set('encoding', event.target.value)}
                disabled={readOnly}
              />
              {errors.encoding && <p className="text-xs text-destructive">{errors.encoding}</p>}
            </div>
            {values.format === 'csv' && (
              <div className="space-y-1.5">
                <Label htmlFor="tpl-delimiter">{t('bpp.bankSettings.delimiter', 'Разделитель колонок')}</Label>
                <Select
                  value={values.delimiter || ';'}
                  onValueChange={(value) => set('delimiter', value)}
                  disabled={readOnly}
                >
                  <SelectTrigger id="tpl-delimiter"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value=";">; {t('bpp.bankSettings.delimiterSemicolon', '(точка с запятой)')}</SelectItem>
                    <SelectItem value=",">, {t('bpp.bankSettings.delimiterComma', '(запятая)')}</SelectItem>
                    <SelectItem value={'\t'}>{t('bpp.bankSettings.delimiterTab', 'Табуляция')}</SelectItem>
                    <SelectItem value="|">| {t('bpp.bankSettings.delimiterPipe', '(вертикальная черта)')}</SelectItem>
                  </SelectContent>
                </Select>
                {errors.delimiter && <p className="text-xs text-destructive">{errors.delimiter}</p>}
              </div>
            )}
            {!isOnec && (
              <>
                <div className="space-y-1.5">
                  <Label htmlFor="tpl-date-format">{t('bpp.bankSettings.dateFormat', 'Формат даты')}</Label>
                  <Input
                    id="tpl-date-format"
                    value={values.date_format}
                    placeholder="ДД.ММ.ГГГГ"
                    onChange={(event) => set('date_format', event.target.value)}
                    disabled={readOnly}
                  />
                  {errors.date_format && <p className="text-xs text-destructive">{errors.date_format}</p>}
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="tpl-amount-mode">{t('bpp.bankSettings.amountMode', 'Сумма в файле')}</Label>
                  <Select
                    value={values.amount_mode}
                    onValueChange={(value) => set('amount_mode', value as AmountMode)}
                    disabled={readOnly}
                  >
                    <SelectTrigger id="tpl-amount-mode"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="signed">
                        {t('bpp.bankSettings.amountSigned', 'Одна колонка суммы со знаком')}
                      </SelectItem>
                      <SelectItem value="split">
                        {t('bpp.bankSettings.amountSplit', 'Колонки «Дебет» и «Кредит»')}
                      </SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </>
            )}
          </div>

          {isOnec ? (
            <p className="rounded-lg border bg-muted/40 p-3 text-sm text-muted-foreground">
              {t('bpp.bankSettings.onecNote', 'Выписка 1С (1CClientBankExchange) разбирается по стандарту формата — колонки в шаблоне ей не нужны.')}
            </p>
          ) : (
            <fieldset className="space-y-2">
              <legend className="text-sm font-medium">
                {t('bpp.bankSettings.columns', 'Заголовки колонок в файле')}
              </legend>
              <p className="text-xs text-muted-foreground">
                {t('bpp.bankSettings.columnsHint', 'Впишите текст заголовка колонки так, как он стоит в файле банка. Регистр и пробелы не важны, порядок колонок и лишние колонки не мешают.')}
              </p>
              <div className="grid gap-3 sm:grid-cols-2">
                {TEMPLATE_FIELDS.filter((field) => !unused.includes(field.key)).map((field) => {
                  const isRequired = required.includes(field.key);
                  const isMissing = missing.some((item) => item.key === field.key);
                  return (
                    <div key={field.key} className="space-y-1.5">
                      <Label htmlFor={`tpl-col-${field.key}`}>
                        {t(field.labelKey, field.label)}
                        {isRequired && <span className="text-destructive"> *</span>}
                      </Label>
                      <Input
                        id={`tpl-col-${field.key}`}
                        value={values.columns[field.key] ?? ''}
                        onChange={(event) => setColumn(field.key, event.target.value)}
                        disabled={readOnly}
                        aria-invalid={isMissing && errors.columns ? true : undefined}
                      />
                    </div>
                  );
                })}
              </div>
              {missing.length > 0 && (
                <p role="status" className="text-sm text-amber-700 dark:text-amber-300">
                  {t('bpp.bankSettings.columnsMissing', 'Не заполнены обязательные колонки: {{names}}', {
                    names: missing.map((field) => `«${t(field.labelKey, field.label)}»`).join(', '),
                  })}
                </p>
              )}
              {errors.columns && missing.length === 0 && (
                <p className="text-sm text-destructive">{errors.columns}</p>
              )}
            </fieldset>
          )}

          {errors.form && <p role="alert" className="text-sm text-destructive">{errors.form}</p>}

          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={onClose} disabled={save.pending}>
              {canEdit ? t('bpp.document.cancel', 'Отмена') : t('bpp.bankSettings.close', 'Закрыть')}
            </Button>
            {canEdit && (
              <Button type="submit" disabled={save.pending}>
                {save.pending && <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />}
                {t('bpp.bankSettings.save', 'Сохранить')}
              </Button>
            )}
          </div>
        </form>

        <section className="space-y-3 border-t pt-4">
          <h3 className="font-medium">{t('bpp.bankSettings.previewTitle', 'Проверить на образце')}</h3>
          {previewBlocked ? (
            <p className="text-sm text-muted-foreground">{previewBlocked}</p>
          ) : (
            <div className="flex flex-wrap items-end gap-2">
              <div className="space-y-1.5">
                <Label htmlFor="tpl-sample">{t('bpp.bankSettings.sample', 'Образец выписки')}</Label>
                <Input
                  id="tpl-sample"
                  type="file"
                  accept={FORMAT_ACCEPT[values.format]}
                  onChange={(event) => { setSample(event.target.files?.[0] ?? null); setPreview(null); }}
                />
              </div>
              <Button type="button" variant="secondary" disabled={!sample || previewing} onClick={runPreview}>
                {previewing
                  ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                  : <FileSearch className="mr-1.5 h-4 w-4" />}
                {t('bpp.bankSettings.previewRun', 'Проверить на образце')}
              </Button>
            </div>
          )}
          {preview && <PreviewResult preview={preview} />}
        </section>
      </CardContent>
      {guard}
    </Card>
  );
}

export default TemplateEditor;
