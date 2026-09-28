/**
 * Словари статусов документов модуля БЗО (ТЗ §15, шапка формы §05, колонка
 * «Статус» реестров §19) — код статуса сервера → подпись и тон бейджа.
 *
 * Вынесено из `StatusBadge.tsx`: файл с компонентом обязан экспортировать
 * только компоненты (`react-refresh/only-export-components`, Fast Refresh),
 * а `STATUS_DICTIONARIES` — обычный объект-константа, не компонент.
 *
 * Подпись зависит от вида документа, а не только от кода: `approved` у
 * заявки — «Утверждена», у бюджета — «Утверждён». Коды — те, что отдаёт
 * сервер (`TextChoices` моделей `apps/bpp/models/*`). Договор, счёт и
 * выписка (этапы 3–4) ещё не заведены на сервере: их коды здесь —
 * предложение по таблицам ТЗ §15.3–15.5, сверить с моделями при их
 * появлении.
 */

/** Тон бейджа — смысл статуса, одинаковый для всех документов. */
export type StatusTone = 'draft' | 'progress' | 'attention' | 'success' | 'danger' | 'muted';

interface StatusDef {
  labelKey: string;
  label: string;
  tone: StatusTone;
}

const s = (labelKey: string, label: string, tone: StatusTone): StatusDef => ({
  labelKey: `bpp.status.${labelKey}`,
  label,
  tone,
});

/** Словари статусов по виду документа: `вид → код → подпись и тон`. */
export const STATUS_DICTIONARIES = {
  // ТЗ §15.1; `BudgetStatus`.
  budget: {
    draft: s('budget.draft', 'Черновик', 'draft'),
    approved: s('budget.approved', 'Утверждён', 'success'),
    closed: s('budget.closed', 'Закрыт', 'muted'),
  },
  // `BudgetVersionStatus`.
  budget_version: {
    draft: s('budgetVersion.draft', 'Черновик', 'draft'),
    active: s('budgetVersion.active', 'Действующая', 'success'),
    archived: s('budgetVersion.archived', 'Архивная', 'muted'),
  },
  // ТЗ §15.2; `RequestStatus`.
  request: {
    draft: s('request.draft', 'Черновик', 'draft'),
    on_review: s('request.on_review', 'На согласовании', 'progress'),
    rework: s('request.rework', 'На доработке', 'attention'),
    rejected: s('request.rejected', 'Отклонена', 'danger'),
    approved: s('request.approved', 'Утверждена', 'success'),
    cancelled: s('request.cancelled', 'Отменена', 'muted'),
    closed: s('request.closed', 'Закрыта', 'muted'),
  },
  // Позиция заявки; `ItemStatus`.
  request_item: {
    open: s('requestItem.open', 'Открыта', 'progress'),
    partially_closed: s('requestItem.partially_closed', 'Частично закрыта', 'attention'),
    closed: s('requestItem.closed', 'Закрыта', 'muted'),
    annulled: s('requestItem.annulled', 'Аннулирована', 'danger'),
  },
  // Подотчёт (B4.1); `AccountableStatus`.
  accountable: {
    draft: s('accountable.draft', 'Черновик', 'draft'),
    on_review: s('accountable.on_review', 'На согласовании', 'progress'),
    awaiting_accounting: s('accountable.awaiting_accounting', 'Ожидает выдачи бухгалтерией', 'attention'),
    awaiting_report: s('accountable.awaiting_report', 'Ожидает авансовый отчёт', 'attention'),
    closed: s('accountable.closed', 'Закрыта', 'muted'),
  },
  // ТЗ §18; `CounterpartyStatus`.
  counterparty: {
    active: s('counterparty.active', 'Активен', 'success'),
    blocked: s('counterparty.blocked', 'Заблокирован', 'danger'),
    archived: s('counterparty.archived', 'Архив', 'muted'),
  },
  // ТЗ §15.3 — коды предложены, модели договора ещё нет (этап 3).
  contract: {
    draft: s('contract.draft', 'Черновик', 'draft'),
    on_review: s('contract.on_review', 'На согласовании', 'progress'),
    rework: s('contract.rework', 'На доработке', 'attention'),
    rejected: s('contract.rejected', 'Отклонён', 'danger'),
    replaced_by_alternative: s('contract.replaced_by_alternative', 'Заменён альтернативой', 'muted'),
    active: s('contract.active', 'Действует', 'success'),
    fulfilled: s('contract.fulfilled', 'Исполнен', 'muted'),
    terminated: s('contract.terminated', 'Расторгнут', 'danger'),
  },
  // ТЗ §15.4 — коды предложены, модели счёта ещё нет (этап 3).
  invoice: {
    draft: s('invoice.draft', 'Черновик', 'draft'),
    under_review: s('invoice.under_review', 'На рассмотрении ФД', 'progress'),
    returned: s('invoice.returned', 'Возвращён на доработку', 'attention'),
    not_payable: s('invoice.not_payable', 'Не к оплате', 'danger'),
    to_pay: s('invoice.to_pay', 'К оплате', 'progress'),
    docs_requested: s('invoice.docs_requested', 'Документы запрошены', 'attention'),
    docs_provided: s('invoice.docs_provided', 'Документы предоставлены', 'progress'),
    paid: s('invoice.paid', 'Оплачено', 'success'),
    cancelled: s('invoice.cancelled', 'Отменён', 'muted'),
  },
  // Фоновая выгрузка реестра (задача 6); `ExportStatus`.
  export: {
    queued: s('export.queued', 'Готовится', 'progress'),
    done: s('export.done', 'Готов', 'success'),
    error: s('export.error', 'Не собран', 'danger'),
  },
} satisfies Record<string, Record<string, StatusDef>>;

export type StatusKind = keyof typeof STATUS_DICTIONARIES;

export type { StatusDef };
