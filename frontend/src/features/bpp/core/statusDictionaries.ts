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
 * сервер (`TextChoices` моделей `apps/bpp/models/*`): договор и счёт — из
 * `agreements.py`/`invoices.py`, загрузка выписки и её строки — из `bank.py`.
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
  // `VersionState`.
  budget_version: {
    draft: s('budgetVersion.draft', 'Черновик', 'draft'),
    active: s('budgetVersion.active', 'Действующая', 'success'),
    archived: s('budgetVersion.archived', 'Архив', 'muted'),
  },
  // ТЗ §15.2; `RequestStatus`.
  request: {
    draft: s('request.draft', 'Черновик', 'draft'),
    in_approval: s('request.in_approval', 'На согласовании', 'progress'),
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
  // ТЗ §15.3; `AgreementStatus` (B3.1).
  contract: {
    draft: s('contract.draft', 'Черновик', 'draft'),
    on_review: s('contract.on_review', 'На согласовании', 'progress'),
    rework: s('contract.rework', 'На доработке', 'attention'),
    rejected: s('contract.rejected', 'Отклонён', 'danger'),
    replaced: s('contract.replaced', 'Заменён альтернативой', 'muted'),
    active: s('contract.active', 'Действует', 'success'),
    fulfilled: s('contract.fulfilled', 'Исполнен', 'muted'),
    terminated: s('contract.terminated', 'Расторгнут', 'danger'),
  },
  // ТЗ §15.4 с D-13 (закрывающие документы после оплаты); `InvoiceStatus` (B3.2).
  invoice: {
    draft: s('invoice.draft', 'Черновик', 'draft'),
    under_review: s('invoice.under_review', 'На рассмотрении ФД', 'progress'),
    returned: s('invoice.returned', 'Возвращён на доработку', 'attention'),
    not_payable: s('invoice.not_payable', 'Не к оплате', 'danger'),
    to_pay: s('invoice.to_pay', 'К оплате', 'progress'),
    partially_paid: s('invoice.partially_paid', 'Оплачено частично', 'attention'),
    paid: s('invoice.paid', 'Оплачено', 'success'),
    awaiting_docs: s('invoice.awaiting_docs', 'Ждёт закрывающих документов', 'attention'),
    docs_provided: s('invoice.docs_provided', 'Документы предоставлены', 'progress'),
    closed: s('invoice.closed', 'Закрыт', 'muted'),
    cancelled: s('invoice.cancelled', 'Отменён', 'muted'),
    replaced: s('invoice.replaced', 'Заменён альтернативой', 'muted'),
  },
  // Загрузка выписки (ТЗ §15.5, A4.1); `BankImportStatus`.
  bank_import: {
    processing: s('bankImport.processing', 'Обрабатывается', 'progress'),
    loaded: s('bankImport.loaded', 'Загружена', 'success'),
    reconciled: s('bankImport.reconciled', 'Сверена', 'success'),
    failed: s('bankImport.failed', 'Ошибка загрузки', 'danger'),
    cancelled: s('bankImport.cancelled', 'Отменена', 'muted'),
  },
  // Строка выписки; `LineMatchStatus` (A4.2).
  bank_line: {
    matched: s('bankLine.matched', 'Сопоставлена', 'success'),
    needs_review: s('bankLine.needs_review', 'Требует проверки', 'attention'),
    excluded: s('bankLine.excluded', 'Исключена', 'muted'),
    unmatched: s('bankLine.unmatched', 'Не сопоставлена', 'attention'),
  },
  // Альтернативное предложение (A5.1, ТЗ §12); `OfferStatus`.
  alternative_offer: {
    draft: s('alternativeOffer.draft', 'Черновик', 'draft'),
    submitted: s('alternativeOffer.submitted', 'Подано', 'progress'),
    selected: s('alternativeOffer.selected', 'Выбрано', 'success'),
    not_selected: s('alternativeOffer.not_selected', 'Не выбрано', 'muted'),
    withdrawn: s('alternativeOffer.withdrawn', 'Отозвано', 'muted'),
    annulled: s('alternativeOffer.annulled', 'Аннулировано', 'danger'),
  },
  // Запись KPI снабжения (A5.2, D-S5-7); `KpiStatus`.
  kpi_record: {
    preliminary: s('kpiRecord.preliminary', 'Предварительный', 'progress'),
    confirmed: s('kpiRecord.confirmed', 'Подтверждён', 'success'),
    annulled: s('kpiRecord.annulled', 'Аннулирован', 'muted'),
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
