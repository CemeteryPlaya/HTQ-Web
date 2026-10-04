/**
 * Форма F-02 «Заявка на закупку» (ТЗ §07): шапка, блок «Бюджет», позиции,
 * вкладки «Согласование», «Файлы», «Исполнение», «История изменений».
 *
 * - Режим и кнопки — из `allowed_actions` сервера; поля правит автор в
 *   «Черновике» и «На доработке» (ТЗ §7.6 п.5).
 * - «Роль инициатора» видна, только если у пользователя обе роли (§7.6 п.1);
 *   смена роли и проекта очищает статью; статьи — строки утверждённого
 *   бюджета проекта в группе роли (`budgets/lines`).
 * - «Остаток после заявки» считается на лету; меньше нуля — предупреждение
 *   текстом ТЗ §7.6 п.4 и нет «Отправить», а «Сохранить черновик» есть.
 * - «На доработке» — комментарий возврата жёлтой плашкой (§7.6 п.6).
 * - «Печать» — PDF через клиент API (JWT), в новой вкладке.
 */
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { AlertTriangle, ArrowLeft } from 'lucide-react';

import { DateInput } from '@/components/ui/date-input';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { Textarea } from '@/components/ui/textarea';
import { errorStatus } from '@/lib/apiError';

import { lessThan, subMoney } from '../budgets/cents';
import { BppDocumentShell, type BppDocumentAction } from '../core/BppDocumentShell';
import { useRegistryBackHref } from '../core/registryBack';
import { formatMoney } from '../format';
import { projectApi, projectKeys } from '../projects/api';
import { refdataApi, refdataKeys } from '../refdata/api';

import {
  bppRequestsApi, REQUEST_HISTORY_TYPE, REQUEST_SUBJECT, REQUESTS_BASE, requestKey,
  type InitiatorRole, type PurchaseRequestCard, type PurchaseType,
} from './api';
import { ItemsEditor } from './ItemsEditor';
import {
  REQUEST_HISTORY_FIELDS, afterRequest, formOf, JUSTIFICATION_MIN, requestInput, submitErrors, totalAmount,
  type RequestFormState,
} from './requestForm';

const COMMENT_MIN = 10;
const ROLE_TITLES: Record<InitiatorRole, string> = { sn: 'Снабженец', pm: 'Руководитель проекта' };

const today = () => new Date().toISOString().slice(0, 10);

function openPdf(blob: Blob) {
  const url = URL.createObjectURL(blob);
  window.open(url, '_blank', 'noopener');
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

function ExecutionTab({ requestId }: { requestId: string }) {
  const { t } = useTranslation();
  const { data, isLoading } = useQuery({
    queryKey: [...requestKey(requestId), 'execution'],
    queryFn: () => bppRequestsApi.execution(requestId),
  });
  if (isLoading) return <Skeleton className="h-24 w-full" />;
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{t('bpp.requests.item', 'Позиция')}</TableHead>
          <TableHead className="text-right">{t('bpp.requests.qtyPlan', 'Кол-во план')}</TableHead>
          <TableHead className="text-right">{t('bpp.requests.qtyAgreements', 'В договорах')}</TableHead>
          <TableHead className="text-right">{t('bpp.requests.qtyInvoices', 'В счетах')}</TableHead>
          <TableHead className="text-right">{t('bpp.requests.amountPlan', 'Сумма план')}</TableHead>
          <TableHead className="text-right">{t('bpp.requests.amountInvoices', 'В счетах')}</TableHead>
          <TableHead className="text-right">{t('bpp.requests.amountPaid', 'Оплачено факт')}</TableHead>
          <TableHead className="text-right">{t('bpp.requests.amountLeft', 'Остаток к закупке')}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {(data ?? []).map((row) => (
          <TableRow key={row.id}>
            <TableCell>
              <div>{row.sys_number}</div>
              <div className="text-xs text-muted-foreground">{row.name}</div>
            </TableCell>
            <TableCell className="text-right">{row.qty}</TableCell>
            <TableCell className="text-right">{row.qty_in_agreements}</TableCell>
            <TableCell className="text-right">{row.qty_in_invoices}</TableCell>
            <TableCell className="text-right">{formatMoney(row.amount)}</TableCell>
            <TableCell className="text-right">{formatMoney(row.amount_in_invoices)}</TableCell>
            <TableCell className="text-right">{formatMoney(row.amount_paid)}</TableCell>
            <TableCell className="text-right">{formatMoney(row.amount_left)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function Field({ label, error, children, htmlFor }: {
  label: string; error?: string; children: ReactNode; htmlFor?: string;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}

export function RequestFormPage() {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();
  const isNew = !id || id === 'new';
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const { data: card, isLoading, error } = useQuery({
    queryKey: requestKey(id ?? 'new'),
    queryFn: () => bppRequestsApi.get(id as string),
    enabled: !isNew,
  });
  const me = useQuery({ queryKey: ['bpp', 'me'], queryFn: bppRequestsApi.me, staleTime: 60_000 });
  const roles = me.data?.initiator_roles ?? [];

  const [form, setForm] = useState<RequestFormState>(() => formOf(undefined, ''));
  const [baseline, setBaseline] = useState('');
  const [showErrors, setShowErrors] = useState(false);

  const cardStamp = card ? `${card.id}:${card.version}` : `new:${roles.join(',')}`;
  useEffect(() => {
    const next = formOf(card, roles.length === 1 ? roles[0] : '');
    setForm(next);
    setBaseline(JSON.stringify(next));
    setShowErrors(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cardStamp]);

  const allowed = useMemo(
    () => (isNew ? ['save', 'submit'] : (card?.allowed_actions ?? [])),
    [isNew, card?.allowed_actions],
  );
  const editable = isNew || allowed.includes('save');
  const dirty = editable && JSON.stringify(form) !== baseline;

  const projects = useQuery({
    queryKey: projectKeys.list('', false),
    queryFn: () => projectApi.list('', false),
    enabled: editable,
    staleTime: 5 * 60 * 1000,
  });
  const uoms = useQuery({
    queryKey: refdataKeys.list('uoms', { active: true }),
    queryFn: () => refdataApi.uoms.list({ active: true }),
    staleTime: 10 * 60 * 1000,
  });
  const role = form.initiator_role;
  const lines = useQuery({
    queryKey: ['bpp', 'budget-lines', form.project_id, role],
    queryFn: () => bppRequestsApi.budgetLines(form.project_id, role as InitiatorRole),
    enabled: editable && Boolean(form.project_id) && Boolean(role),
  });

  const total = totalAmount(form.items);
  const line = lines.data?.find((row) => row.article_id === form.article_id);
  const reserved = Boolean(card?.budget?.reserved) && !editable;
  const budget = editable
    ? (line ? { limit: line.limit, committed: line.committed, available: line.available } : null)
    : card?.budget ?? null;
  const after = budget ? afterRequest(budget.available, total, reserved) : null;
  const overBudget = after !== null && lessThan(after, 0);
  const errors = submitErrors(form, today());
  const currency = card?.currency_code ?? 'KZT';

  const apply = useCallback((saved: PurchaseRequestCard) => {
    queryClient.setQueryData(requestKey(saved.id), saved);
    void queryClient.invalidateQueries({ queryKey: ['bpp', 'history', REQUEST_HISTORY_TYPE, saved.id] });
    void queryClient.invalidateQueries({ queryKey: ['bpp', 'registry', 'requests'] });
    void queryClient.invalidateQueries({ queryKey: ['bpp', 'budget-lines'] });
  }, [queryClient]);

  const save = async (key: string): Promise<PurchaseRequestCard> => {
    if (!form.project_id) {
      setShowErrors(true);
      throw new Error(t('bpp.requests.projectRequired', 'Выберите проект — без него черновик не сохранить'));
    }
    const body = requestInput(form);
    if (isNew) {
      const created = await bppRequestsApi.create(key, body);
      setBaseline(JSON.stringify(form));
      apply(created);
      navigate(`${REQUESTS_BASE}/${created.id}`, { replace: true });
      return created;
    }
    const saved = await bppRequestsApi.save(card!.id, key, { ...body, version: card!.version });
    apply(saved);
    return saved;
  };

  const actions: Record<string, BppDocumentAction> = {
    save: { label: t('bpp.requests.saveDraft', 'Сохранить черновик'), variant: 'outline', run: save },
    submit: {
      label: t('bpp.requests.submit', 'Отправить на согласование'),
      run: async (key) => {
        setShowErrors(true);
        if (Object.keys(errors).length > 0) {
          throw new Error(t('bpp.requests.fixErrors', 'Заполните обязательные поля заявки'));
        }
        const fresh = isNew || dirty ? await save(`${key}-save`) : card!;
        apply(await bppRequestsApi.submit(fresh.id, key, fresh.version));
      },
    },
    withdraw: {
      label: t('bpp.requests.withdraw', 'Отозвать'),
      variant: 'outline',
      confirm: { title: t('bpp.requests.withdrawConfirm', 'Отозвать заявку с согласования? Резерв бюджета будет снят.') },
      run: async (key) => apply(await bppRequestsApi.withdraw(card!.id, key, card!.version)),
    },
    cancel: {
      label: t('bpp.requests.cancel', 'Отменить заявку'),
      variant: 'outline',
      confirm: { title: t('bpp.requests.cancelConfirm', 'Отменить заявку?'), commentMin: COMMENT_MIN },
      run: async (key, comment) =>
        apply(await bppRequestsApi.cancel(card!.id, key, card!.version, comment ?? '')),
    },
    close_remainder: {
      label: t('bpp.requests.closeRemainder', 'Закрыть остаток'),
      variant: 'outline',
      confirm: {
        title: t('bpp.requests.closeRemainderConfirm', 'Закрыть остаток? Невыбранные остатки позиций будут аннулированы.'),
        commentMin: COMMENT_MIN,
      },
      run: async (key, comment) =>
        apply(await bppRequestsApi.closeRemainder(card!.id, key, card!.version, comment ?? '')),
    },
    copy: {
      label: t('bpp.requests.copy', 'Копировать'),
      variant: 'outline',
      run: async (key) => {
        const copy = await bppRequestsApi.copy(card!.id, key);
        apply(copy);
        navigate(`${REQUESTS_BASE}/${copy.id}`);
      },
    },
    delete: {
      label: t('bpp.action.delete', 'Удалить'),
      variant: 'destructive',
      confirm: { title: t('bpp.requests.deleteConfirm', 'Удалить черновик заявки?') },
      run: async (key) => {
        await bppRequestsApi.remove(card!.id, key, card!.version);
        void queryClient.invalidateQueries({ queryKey: ['bpp', 'registry', 'requests'] });
        navigate(REQUESTS_BASE);
      },
    },
    print: {
      label: t('bpp.requests.print', 'Печать (PDF)'),
      variant: 'outline',
      run: async () => openPdf(await bppRequestsApi.print(card!.id)),
    },
  };

  if (!isNew && isLoading) return <Skeleton className="h-64 w-full" />;
  if (!isNew && (error || !card)) {
    return (
      <div className="space-y-2">
        <BackLink />
        <p className="text-sm text-muted-foreground">
          {errorStatus(error) === 404
            ? t('bpp.requests.notFound', 'Заявка не найдена или недоступна.')
            : t('bpp.requests.loadFailed', 'Не удалось загрузить заявку.')}
        </p>
      </div>
    );
  }

  const shown = (key: string) => (showErrors ? errors[key] : undefined);
  const setField = <K extends keyof RequestFormState>(key: K, value: RequestFormState[K]) =>
    setForm((current) => ({ ...current, [key]: value }));
  const shellActions = overBudget ? allowed.filter((action) => action !== 'submit') : allowed;
  const approvedOrLater = card && ['approved', 'closed'].includes(card.status);

  return (
    <div className="space-y-4">
      <BackLink />
      <BppDocumentShell<RequestFormState>
        subjectType={REQUEST_SUBJECT}
        documentId={isNew ? null : card!.id}
        number={card?.number ?? null}
        status={card ? { kind: 'request', code: card.status } : null}
        authorName={card?.author_name ?? null}
        createdAt={card?.created_at ?? null}
        allowedActions={shellActions}
        actions={actions}
        readOnly={!editable}
        historyType={REQUEST_HISTORY_TYPE}
        historyFields={REQUEST_HISTORY_FIELDS}
        extraTabs={approvedOrLater ? [{
          key: 'execution', label: t('bpp.requests.execution', 'Исполнение'),
          content: <ExecutionTab requestId={card!.id} />,
        }] : []}
        draft={editable ? {
          value: form, dirty, onRestore: setForm,
          onSaveDraft: () => save(`draft-${Date.now()}`),
        } : undefined}
      >
        <div className="space-y-6">
          {card?.status === 'rework' && card.rework_comment && (
            <div
              role="status"
              className="flex gap-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm dark:border-amber-800 dark:bg-amber-950/40"
            >
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <div>
                <div className="font-medium">{t('bpp.requests.reworkTitle', 'Заявка возвращена на доработку')}</div>
                <div>{card.rework_comment}</div>
              </div>
            </div>
          )}

          <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {editable && roles.length > 1 && (
              <Field label={t('bpp.requests.role', 'Роль инициатора')} error={shown('initiator_role')}>
                <RadioGroup
                  value={form.initiator_role}
                  onValueChange={(value) => setForm({
                    ...form, initiator_role: value as InitiatorRole, article_id: '',
                  })}
                  className="flex gap-4"
                >
                  {roles.map((value) => (
                    <label key={value} className="flex items-center gap-2 text-sm">
                      <RadioGroupItem value={value} />
                      {ROLE_TITLES[value]}
                    </label>
                  ))}
                </RadioGroup>
              </Field>
            )}
            <Field label={t('bpp.requests.project', 'Проект')} error={shown('project_id')} htmlFor="request-project">
              {editable ? (
                <Select
                  value={form.project_id || undefined}
                  onValueChange={(value) => setForm({ ...form, project_id: value, article_id: '' })}
                >
                  <SelectTrigger id="request-project">
                    <SelectValue placeholder={t('bpp.requests.pickProject', 'Выберите проект')} />
                  </SelectTrigger>
                  <SelectContent>
                    {(projects.data ?? []).filter((p) => p.status === 'active').map((p) => (
                      <SelectItem key={p.id} value={p.id}>{`${p.code} — ${p.name}`}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : (
                <p className="text-sm">{[card!.project.code, card!.project.name].filter(Boolean).join(' — ')}</p>
              )}
            </Field>
            <Field label={t('bpp.requests.article', 'Статья бюджета')} error={shown('article_id')} htmlFor="request-article">
              {editable ? (
                <>
                  <Select
                    value={form.article_id || undefined}
                    disabled={!form.project_id || !role}
                    onValueChange={(value) => setField('article_id', value)}
                  >
                    <SelectTrigger id="request-article">
                      <SelectValue placeholder={form.project_id
                        ? t('bpp.requests.pickArticle', 'Выберите статью')
                        : t('bpp.requests.projectFirst', 'Сначала выберите проект')}
                      />
                    </SelectTrigger>
                    <SelectContent>
                      {(lines.data ?? []).map((row) => (
                        <SelectItem key={row.article_id} value={row.article_id}>
                          {`${row.article_code} — ${row.article_name}`}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  {form.project_id && role && lines.data && lines.data.length === 0 && (
                    <p className="text-xs text-muted-foreground">
                      {t('bpp.requests.noLines',
                        'По проекту нет утверждённых лимитов по вашим статьям. Обратитесь к финансовому директору.')}
                    </p>
                  )}
                </>
              ) : (
                <p className="text-sm">
                  {card!.article ? `${card!.article.code} — ${card!.article.name}` : '—'}
                </p>
              )}
            </Field>
            <Field label={t('bpp.requests.purchaseType', 'Вид закупки')} error={shown('purchase_type')}>
              {editable ? (
                <RadioGroup
                  value={form.purchase_type}
                  onValueChange={(value) => setField('purchase_type', value as PurchaseType)}
                  className="flex gap-4"
                >
                  <label className="flex items-center gap-2 text-sm"><RadioGroupItem value="goods" />ТМЦ</label>
                  <label className="flex items-center gap-2 text-sm"><RadioGroupItem value="works" />Работы и услуги</label>
                </RadioGroup>
              ) : (
                <p className="text-sm">
                  {card!.purchase_type === 'goods' ? 'ТМЦ' : card!.purchase_type === 'works' ? 'Работы и услуги' : '—'}
                </p>
              )}
            </Field>
            <Field label={t('bpp.requests.needDate', 'Потребность к дате')} error={shown('need_date')} htmlFor="request-need">
              {editable ? (
                <DateInput
                  id="request-need" value={form.need_date} min={today()}
                  invalid={Boolean(shown('need_date'))}
                  onChange={(value) => setField('need_date', value)}
                />
              ) : <p className="text-sm">{card!.need_date?.split('-').reverse().join('.') ?? '—'}</p>}
            </Field>
          </section>

          <Field
            label={t('bpp.requests.justification', 'Обоснование потребности')}
            error={shown('justification')}
            htmlFor="request-justification"
          >
            {editable ? (
              <Textarea
                id="request-justification" value={form.justification} maxLength={2000}
                placeholder={t('bpp.requests.justificationHint', 'Не короче {{n}} символов', { n: JUSTIFICATION_MIN })}
                onChange={(event) => setField('justification', event.target.value)}
              />
            ) : <p className="whitespace-pre-wrap text-sm">{card!.justification || '—'}</p>}
          </Field>

          {budget && (
            <section aria-label={t('bpp.requests.budget', 'Бюджет')} className="space-y-2">
              <dl className="grid grid-cols-2 gap-x-4 gap-y-1 rounded-lg border p-3 text-sm sm:grid-cols-4">
                {([
                  [t('bpp.request.limit', 'Лимит статьи'), budget.limit],
                  [t('bpp.request.committed', 'Задействовано'), budget.committed],
                  [t('bpp.request.available', 'Доступный остаток статьи'), budget.available],
                  [reserved
                    ? t('bpp.request.afterReserved', 'Остаток после заявки (уже в резерве)')
                    : t('bpp.request.after', 'Остаток после заявки'), after],
                ] as [string, string | null][]).map(([label, value], index) => (
                  <div key={label}>
                    <dt className="text-xs text-muted-foreground">{label}</dt>
                    <dd
                      data-testid={index === 3 ? 'after-request' : undefined}
                      className={index === 3 && value !== null && lessThan(value, 0)
                        ? 'font-medium text-destructive' : 'font-medium'}
                    >
                      {value === null ? '—' : formatMoney(value, currency)}
                    </dd>
                  </div>
                ))}
              </dl>
              {overBudget && editable && (
                <p role="alert" className="text-sm text-destructive">
                  {t('bpp.requests.overBudget',
                    'Сумма заявки превышает доступный остаток статьи на {{amount}}',
                    { amount: formatMoney(subMoney('0', after as string), currency) })}
                </p>
              )}
            </section>
          )}

          <section className="space-y-2">
            <h3 className="text-lg font-semibold">{t('bpp.requests.items', 'Позиции')}</h3>
            <ItemsEditor
              items={form.items}
              onChange={(items) => setField('items', items)}
              editable={editable}
              uoms={uoms.data ?? []}
              currency={currency}
              defaultNeedDate={form.need_date}
              errors={showErrors ? errors : {}}
            />
          </section>
        </div>
      </BppDocumentShell>
    </div>
  );
}

function BackLink() {
  const { t } = useTranslation();
  const back = useRegistryBackHref(REQUESTS_BASE);
  return (
    <Link
      to={back}
      className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
    >
      <ArrowLeft className="h-4 w-4" />
      {t('bpp.requests.back', 'К заявкам')}
    </Link>
  );
}

export default RequestFormPage;
