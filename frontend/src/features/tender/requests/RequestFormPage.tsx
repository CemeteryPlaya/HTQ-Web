/**
 * Форма заявки на тендер (`/tender/requests/new`, `/tender/requests/:id/edit`;
 * T1.4, план §3.1–3.2, §3.5).
 *
 * - Шапка: роль инициатора (если у пользователя обе роли БЗО — в ней
 *   подаются ЗЗ), проект, статья по умолчанию, вид закупки, дата, адрес,
 *   обоснование, «аналоги» и «частичная поставка».
 * - Позиции — со своей статьей или по статье заявки; доставка и СМР —
 *   переключателями со своей статьёй и плановой суммой (позициями они не
 *   хранятся: сервер строит их при отправке).
 * - Под позициями — подсказка остатка по каждой статье заявки
 *   (`BudgetHint`), сгруппированной так же, как сервер режет заявку на ЗЗ.
 * - Правит автор в «Черновике» и «На доработке» (`allowed_actions`
 *   содержит `save`); иначе — ссылка на карточку. «Сохранить черновик»
 *   требует только проект; «Отправить» — все проверки (`submitErrors`), и
 *   при правках сначала сохраняет, затем отправляет той же версией.
 * - Отказ 409 `E-CON-01` — плашка «заявку уже изменили»; 422 с `fields` —
 *   тексты сервера у полей.
 */
import { useDeferredValue, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { AlertTriangle, Loader2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { DateInput } from '@/components/ui/date-input';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { Textarea } from '@/components/ui/textarea';
import { useIdempotentAction } from '@/features/bpp/core/useIdempotentAction';
import { bppRequestsApi } from '@/features/bpp/requests/api';
import { errorStatus } from '@/lib/apiError';

import { ConflictAlert } from '../core/ConflictAlert';
import { isConflict } from '../core/conflict';
import { fieldErrorsOf, itemFieldErrors, reportFormError } from '../core/fieldErrors';
import {
  TENDER_REQUESTS_BASE, tenderRequestHref, tenderRequestKeys, tenderRequestsApi,
  type InitiatorRole, type PurchaseType, type RequestArticle, type TenderRequestCard,
} from './api';
import { BackToRequests } from './BackToRequests';
import { BudgetHint } from './BudgetHint';
import { ItemsTable } from './ItemsTable';
import { PURCHASE_TYPE_LABELS, ROLE_LABELS } from './labels';
import {
  formOf, JUSTIFICATION_MIN, planByArticle, requestInput, submitErrors, type TenderRequestForm,
} from './requestForm';
import { useArticleNames, useRequestArticles, useRequestProjects, useUoms } from './reference';

const today = () => new Date().toISOString().slice(0, 10);
const ALL_ROLES: InitiatorRole[] = ['sn', 'pm'];

function Field({ label, error, htmlFor, children }: {
  label: string; error?: string; htmlFor?: string; children: ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}

function ArticleSelect({ id, value, onChange, articles, disabled, placeholder }: {
  id: string; value: string; onChange: (value: string) => void; articles: RequestArticle[];
  disabled: boolean; placeholder: string;
}) {
  return (
    <Select value={value || undefined} disabled={disabled} onValueChange={onChange}>
      <SelectTrigger id={id}>
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        {articles.map((article) => (
          <SelectItem key={article.id} value={article.id}>{`${article.code} — ${article.name}`}</SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function CheckField({ id, label, checked, onChange }: {
  id: string; label: string; checked: boolean; onChange: (checked: boolean) => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <Checkbox id={id} checked={checked} onCheckedChange={(value) => onChange(value === true)} />
      <Label htmlFor={id} className="font-normal">{label}</Label>
    </div>
  );
}

export function RequestFormPage() {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();
  const isNew = !id;
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const { data: card, isLoading, error, refetch } = useQuery({
    queryKey: tenderRequestKeys.card(id ?? 'new'),
    queryFn: () => tenderRequestsApi.get(id as string),
    enabled: !isNew,
  });
  // Роли инициатора — роли пользователя в БЗО: в них подаются ЗЗ частей.
  const me = useQuery({ queryKey: ['bpp', 'me'], queryFn: bppRequestsApi.me, staleTime: 60_000 });
  const roles = me.isError ? ALL_ROLES : (me.data?.initiator_roles ?? []);

  const [form, setForm] = useState<TenderRequestForm>(() => formOf(undefined, ''));
  const [baseline, setBaseline] = useState('');
  const [showErrors, setShowErrors] = useState(false);
  // Отказ сервера: поля шапки — по имени, позиции — по ключу строки формы.
  const [serverErrors, setServerErrors] = useState<Record<string, string>>({});
  const [serverItemErrors, setServerItemErrors] = useState<Record<string, string>>({});
  const [projectSearch, setProjectSearch] = useState('');
  const projectQuery = useDeferredValue(projectSearch.trim());
  const [conflict, setConflict] = useState(false);

  const stamp = card ? `${card.id}:${card.version}` : `new:${roles.join(',')}`;
  useEffect(() => {
    const next = formOf(card, roles.length === 1 ? roles[0] : '');
    setForm(next);
    setBaseline(JSON.stringify(next));
    setShowErrors(false);
    setServerErrors({});
    setServerItemErrors({});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stamp]);

  const editable = isNew || Boolean(card?.allowed_actions.includes('save'));
  const dirty = JSON.stringify(form) !== baseline;

  // Сервер отдаёт не больше 20 проектов — выбор идёт поиском, в роли заявки.
  const projects = useRequestProjects(projectQuery, form.initiator_role, editable);
  const projectOptions = useMemo(() => {
    const rows = projects.data ?? [];
    const current = card?.project;
    return current && current.id === form.project_id && !rows.some((row) => row.id === current.id)
      ? [current, ...rows] : rows;
  }, [projects.data, card?.project, form.project_id]);
  const articles = useRequestArticles(form.project_id, form.initiator_role, editable);
  const uoms = useUoms(true);
  const articleNames = useArticleNames();
  const articleList = useMemo(() => articles.data ?? [], [articles.data]);

  const errors = submitErrors(form, today());
  const plan = planByArticle(form);
  const articleLabel = (articleId: string) => {
    const found = articleList.find((article) => article.id === articleId);
    return found ? `${found.code} — ${found.name}` : articleNames.get(articleId) ?? articleId;
  };

  const apply = (saved: TenderRequestCard) => {
    setConflict(false);
    queryClient.setQueryData(tenderRequestKeys.card(saved.id), saved);
    void queryClient.invalidateQueries({ queryKey: [...tenderRequestKeys.all, 'list'] });
  };

  const persist = async (key: string): Promise<TenderRequestCard> => {
    const body = requestInput(form);
    const saved = isNew
      ? await tenderRequestsApi.create(key, body)
      : await tenderRequestsApi.save(card!.id, key, { ...body, version: card!.version });
    setBaseline(JSON.stringify(form));
    apply(saved);
    return saved;
  };

  const handleFailure = (failure: unknown) => {
    if (isConflict(failure)) setConflict(true);
    const all = fieldErrorsOf(failure, t('tender.common.invalidFormat', 'Неверный формат значения'));
    const { fields, items } = itemFieldErrors(all, form.items.map((item) => item.key));
    setServerErrors(fields);
    setServerItemErrors(items);
    if (Object.keys(all).length > 0) setShowErrors(true);
    reportFormError(
      failure,
      t('tender.requests.saveFailed', 'Не удалось сохранить заявку'),
      t('tender.common.invalidFormatToast', 'Сервер не принял формат некоторых полей — проверьте выделенные поля.'),
    );
  };
  const clearServerErrors = () => {
    setServerErrors({});
    setServerItemErrors({});
  };

  const saveAction = useIdempotentAction(async (key) => {
    const saved = await persist(key);
    navigate(tenderRequestHref(saved.id), { replace: isNew });
  });
  const submitAction = useIdempotentAction(async (key) => {
    const fresh = isNew || dirty ? await persist(`${key}-save`) : card!;
    apply(await tenderRequestsApi.submit(fresh.id, key, fresh.version));
    navigate(tenderRequestHref(fresh.id), { replace: isNew });
  });
  const pending = saveAction.pending || submitAction.pending;

  const onSave = () => {
    if (!form.project_id) {
      setShowErrors(true);
      return;
    }
    clearServerErrors();
    saveAction.run().catch(handleFailure);
  };
  const onSubmit = () => {
    setShowErrors(true);
    if (Object.keys(errors).length > 0) return;
    clearServerErrors();
    submitAction.run().catch(handleFailure);
  };

  if (!isNew && isLoading) return <Skeleton className="h-64 w-full" />;
  if (!isNew && (error || !card)) {
    return (
      <div className="space-y-2">
        <BackToRequests />
        <p className="text-sm text-muted-foreground">
          {errorStatus(error) === 404
            ? t('tender.requests.notFound', 'Заявка не найдена или недоступна.')
            : t('tender.requests.loadFailed', 'Не удалось загрузить заявку.')}
        </p>
      </div>
    );
  }
  if (!editable) {
    return (
      <div className="space-y-2">
        <BackToRequests />
        <p className="text-sm text-muted-foreground">
          {t('tender.requests.notEditable', 'Заявку сейчас нельзя править.')}
        </p>
        <Link to={tenderRequestHref(card!.id)} className="text-sm text-primary hover:underline">
          {t('tender.requests.toCard', 'К карточке заявки')}
        </Link>
      </div>
    );
  }

  const shown = (key: string) => serverErrors[key] ?? (showErrors ? errors[key] : undefined);
  const set = <K extends keyof TenderRequestForm>(key: K, value: TenderRequestForm[K]) =>
    setForm((current) => ({ ...current, [key]: value }));
  const noArticles = Boolean(form.project_id && form.initiator_role && articles.data?.length === 0);
  const articlePlaceholder = form.project_id
    ? t('tender.requests.pickArticle', 'Выберите статью')
    : t('tender.requests.projectFirst', 'Сначала выберите проект');
  // Константа, а не `form.initiator_role`: сужение типа доживает до колбэка `map`.
  const hintRole = form.initiator_role;
  const itemErrors: Record<string, string> = {
    ...(showErrors ? errors : {}),
    ...(serverErrors.items ? { items: serverErrors.items } : {}),
    ...Object.fromEntries(Object.entries(serverItemErrors).map(([key, message]) => [`item:${key}`, message])),
  };
  const otherServerErrors = Object.entries(serverErrors)
    .filter(([field]) => !(field in form))
    .map(([, message]) => message);

  return (
    <div className="space-y-6">
      <BackToRequests />
      <h2 className="text-2xl font-bold">
        {isNew
          ? t('tender.requests.newTitle', 'Новая заявка на тендер')
          : t('tender.requests.editTitle', 'Заявка на тендер {{number}}', { number: card!.number })}
      </h2>

      {conflict && (
        <ConflictAlert
          message={t(
            'tender.requests.conflict',
            'Заявку уже изменили — в другом окне или другой пользователь. Обновите её и повторите действие.',
          )}
          onReload={() => { setConflict(false); void refetch(); }}
        />
      )}

      {card?.status === 'rework' && card.rework_comment && (
        <div
          role="status"
          className="flex gap-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm dark:border-amber-800 dark:bg-amber-950/40"
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <div>
            <div className="font-medium">{t('tender.requests.reworkTitle', 'Заявка возвращена на доработку')}</div>
            <div>{card.rework_comment}</div>
          </div>
        </div>
      )}

      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {roles.length > 1 && (
          <Field label={t('tender.requests.role', 'Роль инициатора')} error={shown('initiator_role')}>
            <RadioGroup
              value={form.initiator_role}
              onValueChange={(value) => setForm({ ...form, initiator_role: value as InitiatorRole, article_id: '' })}
              className="flex gap-4"
            >
              {roles.map((value) => (
                <label key={value} className="flex items-center gap-2 text-sm">
                  <RadioGroupItem value={value} />
                  {t(ROLE_LABELS[value].key, ROLE_LABELS[value].fallback)}
                </label>
              ))}
            </RadioGroup>
          </Field>
        )}
        <Field label={t('tender.requests.project', 'Проект')} error={shown('project_id')} htmlFor="tender-request-project">
          <Select
            value={form.project_id || undefined}
            onValueChange={(value) => setForm({
              ...form, project_id: value, article_id: '', delivery_article_id: '', works_article_id: '',
              items: form.items.map((item) => ({ ...item, article_id: '' })),
            })}
          >
            <SelectTrigger id="tender-request-project">
              <SelectValue placeholder={t('tender.requests.pickProject', 'Выберите проект из списка')} />
            </SelectTrigger>
            <SelectContent>
              {projectOptions.map((project) => (
                <SelectItem key={project.id} value={project.id}>{`${project.code} — ${project.name}`}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Input
            type="search" value={projectSearch}
            aria-label={t('tender.requests.projectSearch', 'Поиск проекта')}
            placeholder={t('tender.requests.projectSearchHint', 'Найти проект: код или название')}
            onChange={(event) => setProjectSearch(event.target.value)}
          />
        </Field>
        <Field label={t('tender.requests.article', 'Статья бюджета')} error={shown('article_id')} htmlFor="tender-request-article">
          <ArticleSelect
            id="tender-request-article" value={form.article_id} articles={articleList}
            disabled={!form.project_id || !form.initiator_role} placeholder={articlePlaceholder}
            onChange={(value) => set('article_id', value)}
          />
          {noArticles && (
            <p className="text-xs text-muted-foreground">
              {t('tender.requests.noArticles',
                'По проекту нет утверждённых лимитов по вашим статьям. Обратитесь к финансовому директору.')}
            </p>
          )}
        </Field>
        <Field label={t('tender.requests.purchaseType', 'Вид закупки')} error={shown('purchase_type')}>
          <RadioGroup
            value={form.purchase_type}
            onValueChange={(value) => set('purchase_type', value as PurchaseType)}
            className="flex gap-4"
          >
            {(['goods', 'works'] as const).map((value) => (
              <label key={value} className="flex items-center gap-2 text-sm">
                <RadioGroupItem value={value} />
                {t(PURCHASE_TYPE_LABELS[value].key, PURCHASE_TYPE_LABELS[value].fallback)}
              </label>
            ))}
          </RadioGroup>
        </Field>
        <Field label={t('tender.requests.needDate', 'Потребность к дате')} error={shown('need_date')} htmlFor="tender-request-need">
          <DateInput
            id="tender-request-need" value={form.need_date} min={today()}
            invalid={Boolean(shown('need_date'))}
            onChange={(value) => set('need_date', value)}
          />
        </Field>
        <Field label={t('tender.requests.deliveryAddress', 'Адрес доставки')} error={shown('delivery_address')} htmlFor="tender-request-address">
          <Input
            id="tender-request-address" value={form.delivery_address} maxLength={500}
            onChange={(event) => set('delivery_address', event.target.value)}
          />
        </Field>
      </section>

      <Field
        label={t('tender.requests.justification', 'Обоснование потребности')}
        error={shown('justification')}
        htmlFor="tender-request-justification"
      >
        <Textarea
          id="tender-request-justification" value={form.justification} maxLength={2000}
          placeholder={t('tender.requests.justificationHint', 'Не короче {{n}} символов', { n: JUSTIFICATION_MIN })}
          onChange={(event) => set('justification', event.target.value)}
        />
      </Field>

      <section className="flex flex-wrap gap-6">
        <CheckField
          id="tender-request-analogs" checked={form.allow_analogs}
          label={t('tender.requests.allowAnalogs', 'Допускаются аналоги')}
          onChange={(value) => set('allow_analogs', value)}
        />
        <CheckField
          id="tender-request-partial" checked={form.allow_partial}
          label={t('tender.requests.allowPartial', 'Допускается частичная поставка')}
          onChange={(value) => set('allow_partial', value)}
        />
      </section>

      <section className="space-y-2">
        <h3 className="text-lg font-semibold">{t('tender.requests.items', 'Позиции')}</h3>
        <ItemsTable
          items={form.items}
          onChange={(items) => set('items', items)}
          uoms={uoms.data ?? []}
          articles={articleList}
          defaultNeedDate={form.need_date}
          errors={itemErrors}
        />
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <div className="space-y-3 rounded-2xl border p-4">
          <CheckField
            id="tender-request-delivery" checked={form.needs_delivery}
            label={t('tender.requests.needsDelivery', 'Нужна доставка до объекта')}
            onChange={(value) => set('needs_delivery', value)}
          />
          {form.needs_delivery && (
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label={t('tender.requests.deliveryArticle', 'Статья доставки')} error={shown('delivery_article_id')} htmlFor="tender-request-delivery-article">
                <ArticleSelect
                  id="tender-request-delivery-article" value={form.delivery_article_id} articles={articleList}
                  disabled={!form.project_id || !form.initiator_role} placeholder={articlePlaceholder}
                  onChange={(value) => set('delivery_article_id', value)}
                />
              </Field>
              <Field label={t('tender.requests.deliveryPlan', 'Плановая сумма доставки')} error={shown('delivery_plan_amount')} htmlFor="tender-request-delivery-plan">
                <Input
                  id="tender-request-delivery-plan" inputMode="decimal" className="text-right"
                  value={form.delivery_plan_amount}
                  onChange={(event) => set('delivery_plan_amount', event.target.value)}
                />
              </Field>
            </div>
          )}
        </div>
        <div className="space-y-3 rounded-2xl border p-4">
          <CheckField
            id="tender-request-works" checked={form.needs_works}
            label={t('tender.requests.needsWorks', 'Нужны СМР')}
            onChange={(value) => set('needs_works', value)}
          />
          {form.needs_works && (
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="sm:col-span-2">
                <Field label={t('tender.requests.worksScope', 'Объём работ')} error={shown('works_scope')} htmlFor="tender-request-works-scope">
                  <Textarea
                    id="tender-request-works-scope" value={form.works_scope} maxLength={2000}
                    onChange={(event) => set('works_scope', event.target.value)}
                  />
                </Field>
              </div>
              <Field label={t('tender.requests.worksArticle', 'Статья СМР')} error={shown('works_article_id')} htmlFor="tender-request-works-article">
                <ArticleSelect
                  id="tender-request-works-article" value={form.works_article_id} articles={articleList}
                  disabled={!form.project_id || !form.initiator_role} placeholder={articlePlaceholder}
                  onChange={(value) => set('works_article_id', value)}
                />
              </Field>
              <Field label={t('tender.requests.worksPlan', 'Плановая сумма СМР')} error={shown('works_plan_amount')} htmlFor="tender-request-works-plan">
                <Input
                  id="tender-request-works-plan" inputMode="decimal" className="text-right"
                  value={form.works_plan_amount}
                  onChange={(event) => set('works_plan_amount', event.target.value)}
                />
              </Field>
            </div>
          )}
        </div>
      </section>

      {form.project_id && hintRole && plan.size > 0 && (
        <section className="space-y-2" aria-label={t('tender.requests.budget', 'Остатки статей')}>
          <h3 className="text-lg font-semibold">{t('tender.requests.budget', 'Остатки статей')}</h3>
          <div className="grid gap-2">
            {[...plan.entries()].map(([articleId, amount]) => (
              <BudgetHint
                key={articleId}
                projectId={form.project_id}
                articleId={articleId}
                role={hintRole}
                articleLabel={articleLabel(articleId)}
                plan={amount}
              />
            ))}
          </div>
        </section>
      )}

      {otherServerErrors.length > 0 && (
        <ul className="list-disc space-y-1 pl-5 text-sm text-destructive">
          {otherServerErrors.map((message) => <li key={message}>{message}</li>)}
        </ul>
      )}

      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="outline" disabled={pending} onClick={onSave}>
          {saveAction.pending && <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />}
          {t('tender.requests.saveDraft', 'Сохранить черновик')}
        </Button>
        <Button type="button" disabled={pending} onClick={onSubmit}>
          {submitAction.pending && <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />}
          {t('tender.requests.submit', 'Отправить на согласование')}
        </Button>
        <Button asChild variant="ghost">
          <Link to={isNew ? TENDER_REQUESTS_BASE : tenderRequestHref(card!.id)}>
            {t('tender.requests.discard', 'Отмена')}
          </Link>
        </Button>
      </div>
    </div>
  );
}

export default RequestFormPage;
