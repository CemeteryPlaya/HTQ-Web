/**
 * Форма заявки на подотчётные средства (B4.1): проект и статья бюджета,
 * сумма и цель, ход — выдано, подтверждено авансовыми отчётами, остаток;
 * авансовые отчёты с подтверждающими файлами.
 *
 * - Режим и кнопки — из `allowed_actions`: сумму и цель правит подотчётное
 *   лицо в черновике; «Отметить выдачу» — бухгалтер (`bpp.accountable.payment`)
 *   после согласования; «Добавить авансовый отчёт» — подотчётное лицо, пока
 *   заявка ждёт отчётов.
 * - Отчёт отправляется на согласование своей кнопкой в строке (`can_submit`);
 *   одобренные отчёты, покрывшие сумму, закрывают заявку (сервер).
 * - Файл отчёта — PDF, JPG, PNG до 10 МБ (справочник «Типы файлов»,
 *   `advance_report`); проверка до запроса — `acceptableFile`, последнее
 *   слово — за сервером.
 */
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, Download } from 'lucide-react';

import { newIdempotencyKey } from '@/api/files';
import { acceptableFile } from '@/components/files/fileChecks';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { Textarea } from '@/components/ui/textarea';
import { errorStatus, reportApiError } from '@/lib/apiError';

import { lessThan } from '../budgets/cents';
import { BppDocumentShell, type BppDocumentAction } from '../core/BppDocumentShell';
import { formatDateTime, formatMoney, parseMoneyInput } from '../format';
import { usePrompt, type PromptValues } from '../invoices/PromptDialog';

import {
  ACCOUNTABLE_BASE, ACCOUNTABLE_HISTORY_TYPE, ACCOUNTABLE_SUBJECT, accountableKey,
  bppAccountableApi, type AccountableCard, type AdvanceReportRow,
} from './api';

const REPORT_RULES = { formats: ['.pdf', '.jpg', '.jpeg', '.png'], max_mb: 10 };
/** Состояние согласования отчёта (`signoff.ApprovalState`). */
const REPORT_STATES: Record<string, { label: string; tone: string }> = {
  draft: { label: 'Черновик', tone: 'border-slate-300 text-slate-700' },
  pending: { label: 'На согласовании', tone: 'border-blue-300 text-blue-800' },
  approved: { label: 'Согласован', tone: 'border-emerald-300 text-emerald-800' },
  rejected: { label: 'Отклонён', tone: 'border-red-300 text-red-800' },
  rework: { label: 'На доработке', tone: 'border-amber-300 text-amber-800' },
};
const GOAL_MAX = 2000;

interface FormState {
  amount: string;
  goal: string;
}

const formOf = (card: AccountableCard | undefined): FormState => ({
  amount: card ? formatMoney(card.amount) : '',
  goal: card?.goal ?? '',
});

function Field({ label, children, htmlFor, error }: {
  label: string; children: ReactNode; htmlFor?: string; error?: string;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}

function ReportRow({ report, currency, onSubmit }: {
  report: AdvanceReportRow; currency: string; onSubmit: (report: AdvanceReportRow) => void;
}) {
  const { t } = useTranslation();
  const [opening, setOpening] = useState(false);
  const download = async () => {
    setOpening(true);
    try {
      window.open(await bppAccountableApi.reportFileLink(report.id), '_blank', 'noopener');
    } catch (error) {
      reportApiError(error, t('bpp.accountable.fileFailed', 'Не удалось получить файл отчёта'));
    } finally {
      setOpening(false);
    }
  };
  return (
    <TableRow data-testid="advance-report">
      <TableCell>{report.expense_name}</TableCell>
      <TableCell className="text-right">{formatMoney(report.amount, currency)}</TableCell>
      <TableCell>
        <Badge variant="outline" className={REPORT_STATES[report.approval_state]?.tone}>
          {t(`bpp.accountable.reportState.${report.approval_state}`,
            REPORT_STATES[report.approval_state]?.label ?? report.approval_state)}
        </Badge>
      </TableCell>
      <TableCell>{formatDateTime(report.created_at)}</TableCell>
      <TableCell className="text-right">
        <div className="flex justify-end gap-1">
          {(report.files ?? []).length > 0 && (
            <Button type="button" variant="ghost" size="sm" disabled={opening} onClick={() => void download()}
              aria-label={`${t('bpp.accountable.download', 'Скачать')} ${report.expense_name}`}>
              <Download className="h-4 w-4" />
            </Button>
          )}
          {report.can_submit && (
            <Button type="button" variant="outline" size="sm" onClick={() => onSubmit(report)}>
              {t('bpp.accountable.submitReport', 'Отправить на согласование')}
            </Button>
          )}
        </div>
      </TableCell>
    </TableRow>
  );
}

export function AccountableFormPage() {
  const { t } = useTranslation();
  const { id = '' } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const prompt = usePrompt();

  const { data: card, isLoading, error } = useQuery({
    queryKey: accountableKey(id),
    queryFn: () => bppAccountableApi.get(id),
    enabled: Boolean(id),
  });

  const [form, setForm] = useState<FormState>(() => formOf(undefined));
  const [baseline, setBaseline] = useState('');
  const [showErrors, setShowErrors] = useState(false);
  const stamp = card ? `${card.id}:${card.version}:${card.status}:${card.reports.length}` : '';
  useEffect(() => {
    const next = formOf(card);
    setForm(next);
    setBaseline(JSON.stringify(next));
    setShowErrors(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stamp]);

  const allowed = useMemo(() => card?.allowed_actions ?? [], [card?.allowed_actions]);
  const editable = allowed.includes('save');
  const dirty = editable && JSON.stringify(form) !== baseline;

  const refresh = useCallback(async (saved?: AccountableCard) => {
    if (saved) queryClient.setQueryData(accountableKey(saved.id), saved);
    else await queryClient.invalidateQueries({ queryKey: accountableKey(id) });
    void queryClient.invalidateQueries({ queryKey: ['bpp', 'history', ACCOUNTABLE_HISTORY_TYPE, id] });
    void queryClient.invalidateQueries({ queryKey: ['bpp', 'registry', 'accountable'] });
  }, [id, queryClient]);

  if (isLoading) return <Skeleton className="h-64 w-full" />;
  if (error || !card) {
    return (
      <div className="space-y-2">
        <BackLink />
        <p className="text-sm text-muted-foreground">
          {errorStatus(error) === 404
            ? t('bpp.accountable.notFound', 'Заявка на подотчёт не найдена или недоступна.')
            : t('bpp.accountable.loadError', 'Не удалось загрузить заявку на подотчёт.')}
        </p>
      </div>
    );
  }

  const currency = card.currency;
  const amount = parseMoneyInput(form.amount);
  const errors: Record<string, string> = {};
  if (amount === null || !lessThan('0', amount)) errors.amount = t('bpp.accountable.amountPositive', 'Сумма — больше нуля');
  if (!form.goal.trim()) errors.goal = t('bpp.accountable.goalRequired', 'Укажите цель подотчётных средств');
  const shown = (key: string) => (showErrors ? errors[key] : undefined);
  const version = card.version ?? 0;

  const save = async (key: string): Promise<AccountableCard> => {
    const saved = await bppAccountableApi.save(card.id, key, {
      amount: amount ?? '0.00', goal: form.goal.trim(), version,
    });
    await refresh(saved);
    return saved;
  };

  const addReport = (key: string) => prompt.ask({
    title: t('bpp.accountable.addReportTitle', 'Авансовый отчёт по {{n}}', { n: card.number }),
    description: t('bpp.accountable.addReportHint', 'Остаток к отчёту: {{sum}}', {
      sum: formatMoney(card.remaining_amount, currency),
    }),
    submitLabel: t('bpp.accountable.addReport', 'Добавить отчёт'),
    fields: [
      { key: 'expense_name', kind: 'text', required: true, maxLength: 500,
        label: t('bpp.accountable.expenseName', 'Наименование затрат') },
      { key: 'amount', kind: 'money', required: true,
        label: t('bpp.accountable.reportAmount', 'Сумма, {{c}}', { c: currency }) },
      { key: 'file', kind: 'file', accept: REPORT_RULES.formats.join(','),
        label: t('bpp.accountable.reportFile', 'Подтверждающий документ (PDF, JPG, PNG до 10 МБ)'),
        check: (file) => acceptableFile(t, file, REPORT_RULES) },
    ],
    validate: (values: PromptValues) => {
      const sum = parseMoneyInput(String(values.amount ?? ''));
      if (sum !== null && !lessThan('0', sum)) return t('bpp.accountable.amountPositive', 'Сумма — больше нуля');
      return null;
    },
    submit: async (values) => {
      await bppAccountableApi.addReport(card.id, key, {
        expense_name: String(values.expense_name).trim(),
        amount: parseMoneyInput(String(values.amount)) ?? '0.00',
        file: values.file as File,
      });
      await refresh();
    },
  });

  const submitReport = (report: AdvanceReportRow) => {
    const key = newIdempotencyKey();
    void prompt.ask({
      title: t('bpp.accountable.submitReportTitle', 'Отправить отчёт «{{name}}» на согласование?', {
        name: report.expense_name,
      }),
      submitLabel: t('bpp.accountable.submitReport', 'Отправить на согласование'),
      fields: [],
      submit: async () => {
        await bppAccountableApi.submitReport(report.id, key);
        await refresh();
      },
    });
  };

  const actions: Record<string, BppDocumentAction> = {
    save: { label: t('bpp.action.save', 'Сохранить'), variant: 'outline', run: save },
    submit: {
      label: t('bpp.requests.submit', 'Отправить на согласование'),
      run: async (key) => {
        setShowErrors(true);
        if (Object.keys(errors).length > 0) {
          throw new Error(t('bpp.accountable.fixErrors', 'Заполните сумму и цель'));
        }
        const fresh = dirty ? await save(`${key}-save`) : card;
        await refresh(await bppAccountableApi.submit(fresh.id, key, fresh.version ?? version));
      },
    },
    delete: {
      label: t('bpp.action.delete', 'Удалить'),
      variant: 'destructive',
      confirm: { title: t('bpp.accountable.deleteConfirm', 'Удалить черновик заявки на подотчёт?') },
      run: async (key) => {
        await bppAccountableApi.remove(card.id, key, version);
        void queryClient.invalidateQueries({ queryKey: ['bpp', 'registry', 'accountable'] });
        navigate(ACCOUNTABLE_BASE);
      },
    },
    mark_paid: {
      label: t('bpp.accountable.markPaid', 'Отметить выдачу'),
      confirm: {
        title: t('bpp.accountable.markPaidConfirm', 'Отметить, что {{sum}} выданы подотчётному лицу?', {
          sum: formatMoney(card.amount, currency),
        }),
      },
      run: async (key) => refresh(await bppAccountableApi.markPaid(card.id, key, version)),
    },
    add_report: {
      label: t('bpp.accountable.addReport', 'Добавить отчёт'),
      run: addReport,
    },
  };

  const figures: [string, string][] = [
    [t('bpp.accountable.amount', 'Сумма'), formatMoney(card.amount, currency)],
    [t('bpp.accountable.reported', 'Подтверждено отчётами'), formatMoney(card.reported_amount, currency)],
    [t('bpp.accountable.remaining', 'Остаток к отчёту'), formatMoney(card.remaining_amount, currency)],
  ];

  return (
    <div className="space-y-4">
      <BackLink />
      <BppDocumentShell<FormState>
        subjectType={ACCOUNTABLE_SUBJECT}
        documentId={card.id}
        number={card.number}
        status={{ kind: 'accountable', code: card.status }}
        authorName={card.accountable_user_name ?? null}
        createdAt={card.created_at}
        allowedActions={allowed}
        actions={actions}
        readOnly={!editable}
        withFiles={false}
        historyType={ACCOUNTABLE_HISTORY_TYPE}
        draft={editable ? {
          value: form, dirty, onRestore: setForm, onSaveDraft: () => save(`draft-${Date.now()}`),
        } : undefined}
      >
        <div className="space-y-6">
          <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <Field label={t('bpp.accountable.project', 'Проект / статья')}>
              <p className="text-sm">
                {[card.project?.code, card.project?.name].filter(Boolean).join(' — ') || '—'} / {card.article_name}
              </p>
            </Field>
            <Field label={t('bpp.accountable.amount', 'Сумма')} htmlFor="acc-form-amount" error={shown('amount')}>
              {editable ? (
                <Input id="acc-form-amount" className="text-right" inputMode="decimal" value={form.amount}
                  onChange={(event) => setForm({ ...form, amount: event.target.value })}
                  onBlur={() => { if (amount !== null) setForm({ ...form, amount: formatMoney(amount) }); }} />
              ) : <p className="text-sm">{formatMoney(card.amount, currency)}</p>}
            </Field>
            {card.paid_at && (
              <Field label={t('bpp.accountable.paid', 'Выдано')}>
                <p className="text-sm">
                  {formatDateTime(card.paid_at)}{card.paid_by_name ? ` · ${card.paid_by_name}` : ''}
                </p>
              </Field>
            )}
          </section>
          <Field label={t('bpp.accountable.goal', 'Цель')} htmlFor="acc-form-goal" error={shown('goal')}>
            {editable ? (
              <Textarea id="acc-form-goal" rows={3} maxLength={GOAL_MAX} value={form.goal}
                onChange={(event) => setForm({ ...form, goal: event.target.value })} />
            ) : <p className="whitespace-pre-line text-sm">{card.goal}</p>}
          </Field>

          {card.status !== 'draft' && (
            <dl className="grid grid-cols-3 gap-3 rounded-lg border p-3">
              {figures.map(([label, value]) => (
                <div key={label}>
                  <dt className="text-xs text-muted-foreground">{label}</dt>
                  <dd className="text-sm font-medium">{value}</dd>
                </div>
              ))}
            </dl>
          )}

          {(card.reports.length > 0 || allowed.includes('add_report')) && (
            <section className="space-y-2">
              <h3 className="text-lg font-semibold">{t('bpp.accountable.reports', 'Авансовые отчёты')}</h3>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t('bpp.accountable.expenseName', 'Наименование затрат')}</TableHead>
                    <TableHead className="text-right">{t('bpp.accountable.amount', 'Сумма')}</TableHead>
                    <TableHead>{t('bpp.registry.status', 'Статус')}</TableHead>
                    <TableHead>{t('bpp.accountable.addedAt', 'Добавлен')}</TableHead>
                    <TableHead />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {card.reports.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={5} className="text-center text-muted-foreground">
                        {t('bpp.accountable.noReports', 'Отчётов пока нет — добавьте первый кнопкой «Добавить отчёт».')}
                      </TableCell>
                    </TableRow>
                  )}
                  {card.reports.map((report) => (
                    <ReportRow key={report.id} report={report} currency={currency} onSubmit={submitReport} />
                  ))}
                </TableBody>
              </Table>
            </section>
          )}
        </div>
      </BppDocumentShell>
      {prompt.dialog}
    </div>
  );
}

function BackLink() {
  const { t } = useTranslation();
  return (
    <Link to={ACCOUNTABLE_BASE} className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
      <ArrowLeft className="h-4 w-4" />
      {t('bpp.accountable.back', 'К подотчёту')}
    </Link>
  );
}

export default AccountableFormPage;
