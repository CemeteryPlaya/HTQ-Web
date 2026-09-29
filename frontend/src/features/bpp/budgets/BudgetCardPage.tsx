/**
 * Форма F-01 «Бюджет проекта» (ТЗ §06): проект и валюта, лимиты по статьям,
 * итоги по бюджету и по группам статей, вкладки «Версии» и «История».
 *
 * Режим формы определяет сервер (`allowed_actions`):
 * - **Создание** (`/bpp/budgets/new`) и **Черновик** — таблица лимитов
 *   правится целиком, «Сохранить», «Утвердить», «Удалить»;
 * - **Утверждён** — только чтение с «Задействовано» и «Доступно»;
 *   «Корректировать», «Закрыть бюджет»;
 * - **Корректировка** — лимиты и новые строки; статья существующей строки не
 *   меняется; комментарий ≥ 10 символов обязателен; лимит ниже
 *   «Задействовано» подсвечивается и закрывает «Утвердить корректировку»
 *   (ТЗ §6.5 п.3) — сервер проверяет то же под блокировкой (E-BUD-05);
 * - **Закрыт** — «Открыть повторно».
 *
 * Итоги пересчитываются на лету в копейках (`cents.ts`), без `float`.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, Plus, Trash2 } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table, TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { Textarea } from '@/components/ui/textarea';
import { errorCode, errorStatus } from '@/lib/apiError';
import { cn } from '@/lib/utils';

import { BppDocumentShell, type BppDocumentAction } from '../core/BppDocumentShell';
import { StatusBadge } from '../core/StatusBadge';
import { formatDateTime, formatMoney, parseMoneyInput } from '../format';
import { projectApi, projectKeys } from '../projects/api';
import { refdataApi, refdataKeys } from '../refdata/api';

import {
  BUDGET_HISTORY_TYPE, BUDGETS_BASE, budgetApi, budgetKey, type BudgetCard,
} from './api';
import {
  COMMENT_MIN, emptyLine, formOf, lineOf, linesInput, validateLines,
  type BudgetFormState, type EditLine,
} from './budgetForm';
import { lessThan, subMoney, sumMoney, toCents } from './cents';

const SUBJECT = 'bpp.budget';

function useArticles() {
  const articles = useQuery({
    queryKey: refdataKeys.list('articles', { active: true }),
    queryFn: () => refdataApi.articles.list({ active: true }),
    staleTime: 5 * 60 * 1000,
  });
  const groups = useQuery({
    queryKey: refdataKeys.list('articleGroups'),
    queryFn: () => refdataApi.articleGroups.list(),
    staleTime: 5 * 60 * 1000,
  });
  return useMemo(() => {
    const groupName = new Map((groups.data ?? []).map((group) => [group.id, group.name]));
    return (articles.data ?? []).map((article) => ({
      id: article.id,
      label: `${article.code} — ${article.name}`,
      group: groupName.get(article.group_id) ?? '',
    }));
  }, [articles.data, groups.data]);
}

function LinesEditor({
  lines, onChange, editable, correction, showCommitted, currency, errors, archivedNames,
}: {
  lines: EditLine[];
  onChange: (lines: EditLine[]) => void;
  editable: boolean;
  correction: boolean;
  showCommitted: boolean;
  currency: string;
  errors: Record<string, string>;
  archivedNames: Record<string, { name: string; group: string; archived: boolean }>;
}) {
  const { t } = useTranslation();
  const articles = useArticles();
  const byId = useMemo(() => new Map(articles.map((a) => [a.id, a])), [articles]);

  const patch = (key: string, change: Partial<EditLine>) =>
    onChange(lines.map((line) => (line.key === key ? { ...line, ...change } : line)));

  const limitsTotal = sumMoney(lines.map((line) => parseMoneyInput(line.limit)));
  const committedTotal = sumMoney(lines.map((line) => line.committed));

  return (
    <div className="space-y-2">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-10">№</TableHead>
            <TableHead>{t('bpp.budgets.article', 'Статья бюджета')}</TableHead>
            <TableHead>{t('bpp.budgets.group', 'Группа')}</TableHead>
            <TableHead className="text-right">{t('bpp.budgets.lineLimit', 'Лимит')}</TableHead>
            {showCommitted && (
              <>
                <TableHead className="text-right">{t('bpp.budgets.committedCol', 'Задействовано')}</TableHead>
                <TableHead className="text-right">{t('bpp.budgets.availableCol', 'Доступно')}</TableHead>
              </>
            )}
            <TableHead>{t('bpp.budgets.lineComment', 'Комментарий')}</TableHead>
            {editable && <TableHead className="w-20" />}
          </TableRow>
        </TableHeader>
        <TableBody>
          {lines.length === 0 && (
            <TableRow>
              <TableCell colSpan={8} className="text-center text-muted-foreground">
                {t('bpp.budgets.noLines', 'Строк нет — добавьте статью')}
              </TableCell>
            </TableRow>
          )}
          {lines.map((line, index) => {
            const known = byId.get(line.article_id) ?? null;
            const shown = archivedNames[line.article_id];
            const amount = parseMoneyInput(line.limit);
            const available = line.committed !== null && amount !== null
              ? subMoney(amount, line.committed) : null;
            const error = errors[line.key];
            return (
              <TableRow key={line.key} data-testid="budget-line">
                <TableCell>{index + 1}</TableCell>
                <TableCell className="min-w-64">
                  {editable && !line.locked ? (
                    <Select
                      value={line.article_id || undefined}
                      onValueChange={(value) => patch(line.key, { article_id: value })}
                    >
                      <SelectTrigger aria-label={t('bpp.budgets.article', 'Статья бюджета')}>
                        <SelectValue placeholder={t('bpp.budgets.pickArticle', 'Выберите статью')} />
                      </SelectTrigger>
                      <SelectContent>
                        {articles.map((article) => (
                          <SelectItem key={article.id} value={article.id}>{article.label}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  ) : (
                    <span>
                      {known?.label ?? shown?.name ?? line.article_id}
                      {shown?.archived && (
                        <Badge variant="outline" className="ml-2">{t('bpp.common.archive', 'Архив')}</Badge>
                      )}
                    </span>
                  )}
                  {error && <p className="mt-1 text-xs text-destructive">{error}</p>}
                </TableCell>
                <TableCell className="text-muted-foreground">{known?.group ?? shown?.group ?? ''}</TableCell>
                <TableCell className="text-right">
                  {editable ? (
                    <Input
                      className={cn('text-right', error && line.article_id && 'border-destructive')}
                      value={line.limit}
                      inputMode="decimal"
                      aria-label={t('bpp.budgets.lineLimit', 'Лимит')}
                      onChange={(event) => patch(line.key, { limit: event.target.value })}
                      onBlur={() => {
                        const parsed = parseMoneyInput(line.limit);
                        if (parsed !== null) patch(line.key, { limit: formatMoney(parsed) });
                      }}
                    />
                  ) : formatMoney(amount ?? '0', currency)}
                </TableCell>
                {showCommitted && (
                  <>
                    <TableCell className="text-right">
                      {line.committed === null ? '—' : formatMoney(line.committed, currency)}
                    </TableCell>
                    <TableCell className={`text-right ${available && lessThan(available, 0) ? 'text-destructive' : ''}`}>
                      {available === null ? '—' : formatMoney(available, currency)}
                    </TableCell>
                  </>
                )}
                <TableCell>
                  {editable ? (
                    <Input
                      value={line.comment}
                      maxLength={255}
                      aria-label={t('bpp.budgets.lineComment', 'Комментарий')}
                      onChange={(event) => patch(line.key, { comment: event.target.value })}
                    />
                  ) : line.comment}
                </TableCell>
                {editable && (
                  <TableCell>
                    <div className="flex gap-1">
                      {!line.locked && (
                        <Button
                          type="button"
                          size="icon"
                          variant="ghost"
                          aria-label={t('bpp.budgets.removeLine', 'Удалить строку')}
                          disabled={line.committed !== null && toCents(line.committed) !== 0n}
                          onClick={() => onChange(lines.filter((l) => l.key !== line.key))}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      )}
                    </div>
                  </TableCell>
                )}
              </TableRow>
            );
          })}
        </TableBody>
        <TableFooter>
          <TableRow>
            <TableCell />
            <TableCell colSpan={2}>{t('bpp.budgets.total', 'Итого')}</TableCell>
            <TableCell className="text-right">{formatMoney(limitsTotal, currency)}</TableCell>
            {showCommitted && (
              <>
                <TableCell className="text-right">{formatMoney(committedTotal, currency)}</TableCell>
                <TableCell className="text-right">
                  {formatMoney(subMoney(limitsTotal, committedTotal), currency)}
                </TableCell>
              </>
            )}
            <TableCell colSpan={editable ? 2 : 1} />
          </TableRow>
        </TableFooter>
      </Table>
      {editable && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => onChange([...lines, emptyLine(correction)])}
        >
          <Plus className="mr-1.5 h-4 w-4" />
          {t('bpp.budgets.addLine', 'Добавить статью')}
        </Button>
      )}
    </div>
  );
}

function GroupTotals({ card }: { card: BudgetCard }) {
  const { t } = useTranslation();
  if (!card.active_version || card.totals.by_group.length === 0) return null;
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {card.totals.by_group.map((group) => (
        <dl key={group.group_code} className="rounded-lg border p-3 text-sm">
          <dt className="mb-1 font-medium">{group.group_name}</dt>
          <dd className="grid grid-cols-3 gap-2">
            <span>{t('bpp.budgets.lineLimit', 'Лимит')}: {formatMoney(group.limit_amount, card.currency_code)}</span>
            <span>{t('bpp.budgets.committedCol', 'Задействовано')}: {formatMoney(group.committed, card.currency_code)}</span>
            <span className={lessThan(group.available, 0) ? 'text-destructive' : undefined}>
              {t('bpp.budgets.availableCol', 'Доступно')}: {formatMoney(group.available, card.currency_code)}
            </span>
          </dd>
        </dl>
      ))}
    </div>
  );
}

function VersionsTab({ budgetId }: { budgetId: string }) {
  const { t } = useTranslation();
  const { data, isLoading } = useQuery({
    queryKey: [...budgetKey(budgetId), 'versions'],
    queryFn: () => budgetApi.versions(budgetId),
  });
  if (isLoading) return <Skeleton className="h-24 w-full" />;
  if (!data || data.length === 0) {
    return <p className="text-sm text-muted-foreground">{t('bpp.budgets.noVersions', 'Утверждённых версий пока нет')}</p>;
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{t('bpp.budgets.version', 'Версия')}</TableHead>
          <TableHead>{t('bpp.registry.status', 'Статус')}</TableHead>
          <TableHead>{t('bpp.budgets.approvedAt', 'Утверждён')}</TableHead>
          <TableHead>{t('bpp.budgets.approvedBy', 'Утвердил')}</TableHead>
          <TableHead>{t('bpp.budgets.correctionComment', 'Комментарий к корректировке')}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {data.map((version) => (
          <TableRow key={version.id}>
            <TableCell>{version.version_no}</TableCell>
            <TableCell><StatusBadge kind="budget_version" status={version.state} /></TableCell>
            <TableCell>{formatDateTime(version.approved_at)}</TableCell>
            <TableCell>{version.approved_by_name ?? '—'}</TableCell>
            <TableCell>{version.comment || '—'}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

export function BudgetCardPage() {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();
  const isNew = !id || id === 'new';
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const { data: card, isLoading, error } = useQuery({
    queryKey: budgetKey(id ?? 'new'),
    queryFn: () => budgetApi.get(id as string),
    enabled: !isNew,
  });

  const projects = useQuery({
    queryKey: projectKeys.list('', false),
    queryFn: () => projectApi.list('', false),
    enabled: isNew,
    staleTime: 5 * 60 * 1000,
  });
  const currencies = useQuery({
    queryKey: refdataKeys.list('currencies', { active: true }),
    queryFn: () => refdataApi.currencies.list({ active: true }),
    enabled: isNew,
    staleTime: 10 * 60 * 1000,
  });

  const [form, setForm] = useState<BudgetFormState>(() => formOf(undefined));
  const [baseline, setBaseline] = useState('');
  const [showErrors, setShowErrors] = useState(false);
  const [existingId, setExistingId] = useState<string | null>(null);

  // Карточка пришла или обновилась после действия — форма начинается с неё.
  const cardStamp = card ? `${card.id}:${card.version}:${card.correction ? 'c' : ''}` : 'new';
  useEffect(() => {
    const next = formOf(card);
    setForm(next);
    setBaseline(JSON.stringify(next));
    setShowErrors(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cardStamp]);

  const allowed = useMemo(
    () => (isNew ? ['save'] : (card?.allowed_actions ?? [])),
    [isNew, card?.allowed_actions],
  );
  const correction = Boolean(card?.correction);
  const editable = isNew || allowed.includes('save') || allowed.includes('save_correction');
  const dirty = editable && JSON.stringify(form) !== baseline;
  const lineErrors = validateLines(form.lines, { correction });
  const hasErrors = Object.keys(lineErrors).length > 0
    || (isNew && !form.project_id)
    || (correction && form.comment.trim().length < COMMENT_MIN);

  const apply = useCallback((saved: BudgetCard) => {
    queryClient.setQueryData(budgetKey(saved.id), saved);
    void queryClient.invalidateQueries({ queryKey: ['bpp', 'history', BUDGET_HISTORY_TYPE, saved.id] });
    void queryClient.invalidateQueries({ queryKey: [...budgetKey(saved.id), 'versions'] });
    void queryClient.invalidateQueries({ queryKey: ['bpp', 'registry', 'budgets'] });
  }, [queryClient]);

  const requireValid = () => {
    setShowErrors(true);
    if (hasErrors) {
      throw new Error(t('bpp.budgets.fixErrors', 'Исправьте ошибки в строках бюджета'));
    }
  };

  const saveDraft = async (key: string): Promise<BudgetCard> => {
    requireValid();
    if (isNew) {
      try {
        const created = await budgetApi.create(key, {
          project_id: form.project_id, currency: form.currency, lines: linesInput(form.lines),
        });
        setBaseline(JSON.stringify(form));
        apply(created);
        navigate(`${BUDGETS_BASE}/${created.id}`, { replace: true });
        return created;
      } catch (err) {
        if (errorCode(err) === 'E-BUD-03') {
          const fields = (err as { response?: { data?: { fields?: { existing_id?: string }[] } } })
            .response?.data?.fields;
          setExistingId(fields?.[0]?.existing_id ?? null);
        }
        throw err;
      }
    }
    const saved = await budgetApi.save(card!.id, key, {
      version: card!.version, lines: linesInput(form.lines),
    });
    apply(saved);
    return saved;
  };

  const actions: Record<string, BppDocumentAction> = {
    save: { label: t('bpp.action.save', 'Сохранить'), variant: 'outline', run: (key) => saveDraft(key) },
    approve: {
      label: t('bpp.budgets.approve', 'Утвердить'),
      confirm: { title: t('bpp.budgets.approveConfirm', 'Утвердить бюджет? Статьи станут доступны для заявок.') },
      run: async (key) => {
        const fresh = dirty ? await saveDraft(`${key}-save`) : card!;
        apply(await budgetApi.approve(fresh.id, key, fresh.version));
      },
    },
    delete: {
      label: t('bpp.action.delete', 'Удалить'),
      variant: 'destructive',
      confirm: { title: t('bpp.budgets.deleteConfirm', 'Удалить черновик бюджета?') },
      run: async (key) => {
        await budgetApi.remove(card!.id, key, card!.version);
        void queryClient.invalidateQueries({ queryKey: ['bpp', 'registry', 'budgets'] });
        navigate(BUDGETS_BASE);
      },
    },
    start_correction: {
      label: t('bpp.budgets.startCorrection', 'Корректировать'),
      run: async (key) => apply(await budgetApi.startCorrection(card!.id, key, card!.version)),
    },
    save_correction: {
      label: t('bpp.action.save', 'Сохранить'),
      variant: 'outline',
      run: async (key) => {
        requireValid();
        apply(await budgetApi.saveCorrection(card!.id, key, {
          version: card!.version, lines: linesInput(form.lines), comment: form.comment.trim(),
        }));
      },
    },
    approve_correction: {
      label: t('bpp.budgets.approveCorrection', 'Утвердить корректировку'),
      run: async (key) => {
        requireValid();
        let fresh = card!;
        if (dirty) {
          fresh = await budgetApi.saveCorrection(fresh.id, `${key}-save`, {
            version: fresh.version, lines: linesInput(form.lines), comment: form.comment.trim(),
          });
        }
        apply(await budgetApi.approveCorrection(fresh.id, key, fresh.version, form.comment.trim()));
      },
    },
    cancel_correction: {
      label: t('bpp.budgets.cancelCorrection', 'Отменить корректировку'),
      variant: 'outline',
      confirm: { title: t('bpp.budgets.cancelCorrectionConfirm', 'Отменить корректировку? Черновик версии будет удалён.') },
      run: async (key) => apply(await budgetApi.cancelCorrection(card!.id, key, card!.version)),
    },
    close: {
      label: t('bpp.budgets.close', 'Закрыть бюджет'),
      variant: 'outline',
      confirm: {
        title: t('bpp.budgets.closeConfirm', 'Закрыть бюджет? Новые заявки по проекту будут запрещены.'),
        commentMin: COMMENT_MIN,
      },
      run: async (key, comment) => apply(await budgetApi.close(card!.id, key, card!.version, comment ?? '')),
    },
    reopen: {
      label: t('bpp.budgets.reopen', 'Открыть повторно'),
      variant: 'outline',
      confirm: { title: t('bpp.budgets.reopenConfirm', 'Открыть бюджет повторно?'), commentMin: COMMENT_MIN },
      run: async (key, comment) => apply(await budgetApi.reopen(card!.id, key, card!.version, comment ?? '')),
    },
  };

  if (!isNew && isLoading) return <Skeleton className="h-64 w-full" />;
  if (!isNew && (error || !card)) {
    return (
      <div className="space-y-2">
        <BackLink />
        <p className="text-sm text-muted-foreground">
          {errorStatus(error) === 404
            ? t('bpp.budgets.notFound', 'Бюджет не найден или недоступен.')
            : t('bpp.budgets.loadFailed', 'Не удалось загрузить бюджет.')}
        </p>
      </div>
    );
  }

  const shownLines = correction ? card!.correction!.lines : card?.lines ?? [];
  const names = Object.fromEntries(shownLines.map((line) => [line.article_id, {
    name: `${line.article_code} — ${line.article_name}`, group: line.group_name,
    archived: line.article_archived,
  }]));
  const project = isNew ? projects.data?.find((p) => p.id === form.project_id) : card!.project;
  const shellActions = allowed.filter((action) => action !== 'export');
  const approveBlocked = correction && Object.keys(lineErrors).length > 0;

  return (
    <div className="space-y-4">
      <BackLink />
      <BppDocumentShell<BudgetFormState>
        subjectType={SUBJECT}
        documentId={isNew ? null : card!.id}
        number={card?.number ?? null}
        status={card ? { kind: 'budget', code: card.status } : null}
        authorName={card?.created_by_name ?? null}
        createdAt={card?.created_at ?? null}
        allowedActions={approveBlocked
          ? shellActions.filter((action) => action !== 'approve_correction')
          : shellActions}
        actions={actions}
        readOnly={!editable}
        withApproval={false}
        withFiles={false}
        historyType={BUDGET_HISTORY_TYPE}
        extraTabs={isNew ? [] : [{
          key: 'versions', label: t('bpp.budgets.versions', 'Версии'),
          content: <VersionsTab budgetId={card!.id} />,
        }]}
        draft={editable ? {
          value: form,
          dirty,
          onRestore: setForm,
          onSaveDraft: () => (correction
            ? actions.save_correction.run(`draft-${Date.now()}`)
            : saveDraft(`draft-${Date.now()}`)),
        } : undefined}
      >
        <div className="space-y-6">
          <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div className="space-y-1.5 sm:col-span-2">
              <Label htmlFor="budget-project">{t('bpp.budgets.project', 'Проект')}</Label>
              {isNew ? (
                <Select
                  value={form.project_id || undefined}
                  onValueChange={(value) => { setExistingId(null); setForm({ ...form, project_id: value }); }}
                >
                  <SelectTrigger id="budget-project">
                    <SelectValue placeholder={t('bpp.budgets.pickProject', 'Выберите проект')} />
                  </SelectTrigger>
                  <SelectContent>
                    {(projects.data ?? []).filter((p) => p.status === 'active').map((p) => (
                      <SelectItem key={p.id} value={p.id}>{`${p.code} — ${p.name}`}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : (
                <p className="text-sm font-medium">
                  {[project?.code, project?.name].filter(Boolean).join(' — ') || '—'}
                </p>
              )}
              {showErrors && isNew && !form.project_id && (
                <p className="text-xs text-destructive">{t('bpp.budgets.projectRequired', 'Выберите проект')}</p>
              )}
              {existingId && (
                <p className="text-xs">
                  <Link className="text-primary underline" to={`${BUDGETS_BASE}/${existingId}`}>
                    {t('bpp.budgets.openExisting', 'Открыть существующий бюджет')}
                  </Link>
                </p>
              )}
            </div>
            <div className="space-y-1.5">
              <Label>{t('bpp.budgets.customer', 'Заказчик проекта')}</Label>
              <p className="text-sm">{project?.customer_name || '—'}</p>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="budget-currency">{t('bpp.budgets.currency', 'Валюта бюджета')}</Label>
              {isNew ? (
                <Select value={form.currency} onValueChange={(value) => setForm({ ...form, currency: value })}>
                  <SelectTrigger id="budget-currency"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {(currencies.data ?? [{ id: 'KZT', code: 'KZT', name: 'Тенге' }]).map((c) => (
                      <SelectItem key={c.code} value={c.code}>{c.code}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : <p className="text-sm">{card!.currency_code}</p>}
            </div>
            {!isNew && (
              <div className="space-y-1.5">
                <Label>{t('bpp.budgets.version', 'Версия')}</Label>
                <p className="text-sm">
                  {card!.active_version?.version_no ?? 1}
                  {correction && (
                    <Badge variant="outline" className="ml-2">
                      {t('bpp.budgets.correctionDraft', 'корректировка — версия {{n}}', {
                        n: card!.correction!.version_no,
                      })}
                    </Badge>
                  )}
                </p>
              </div>
            )}
          </section>

          {correction && (
            <section className="space-y-1.5">
              <Label htmlFor="budget-comment">
                {t('bpp.budgets.correctionComment', 'Комментарий к корректировке')}
              </Label>
              <Textarea
                id="budget-comment"
                value={form.comment}
                maxLength={1000}
                disabled={!editable}
                onChange={(event) => setForm({ ...form, comment: event.target.value })}
              />
              {showErrors && form.comment.trim().length < COMMENT_MIN && (
                <p className="text-xs text-destructive">
                  {t('bpp.common.commentMin', 'Комментарий — не короче {{n}} символов', { n: COMMENT_MIN })}
                </p>
              )}
            </section>
          )}

          <section className="space-y-2">
            <h3 className="text-lg font-semibold">{t('bpp.budgets.lines', 'Лимиты по статьям')}</h3>
            <LinesEditor
              lines={editable ? form.lines : shownLines.map((line) => lineOf(line, true))}
              onChange={(lines) => setForm({ ...form, lines })}
              editable={editable}
              correction={correction}
              showCommitted={Boolean(card?.active_version)}
              currency={card?.currency_code ?? form.currency}
              errors={showErrors || correction ? lineErrors : {}}
              archivedNames={names}
            />
          </section>

          {card && <GroupTotals card={card} />}
        </div>
      </BppDocumentShell>
    </div>
  );
}

function BackLink() {
  const { t } = useTranslation();
  return (
    <Link
      to={BUDGETS_BASE}
      className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
    >
      <ArrowLeft className="h-4 w-4" />
      {t('bpp.budgets.back', 'К бюджетам')}
    </Link>
  );
}

export default BudgetCardPage;
