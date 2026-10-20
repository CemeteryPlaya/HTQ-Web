/**
 * Подписи и тона статусов документов тендерного модуля (план этапов 0–2
 * §3.1 `TenderRequestStatus`, §4.1 `TenderStatus` и статусы приглашения).
 * Тона — те же, что у бейджей БЗО, чтобы «На согласовании» выглядело
 * одинаково в обоих разделах.
 *
 * Отдельно от компонента бейджа: файл с компонентом экспортирует только
 * компоненты (`react-refresh/only-export-components`).
 */
export type StatusTone = 'draft' | 'progress' | 'attention' | 'success' | 'danger' | 'muted';

export interface StatusDef {
  labelKey: string;
  label: string;
  tone: StatusTone;
}

const dictionary = (kind: string) => (code: string, label: string, tone: StatusTone): StatusDef => ({
  labelKey: `tender.status.${kind}.${code}`,
  label,
  tone,
});

const r = dictionary('request');
export const TENDER_REQUEST_STATUSES: Record<string, StatusDef> = {
  draft: r('draft', 'Черновик', 'draft'),
  in_approval: r('in_approval', 'На согласовании', 'progress'),
  approved: r('approved', 'Утверждена', 'success'),
  rework: r('rework', 'На доработке', 'attention'),
  rejected: r('rejected', 'Отклонена', 'danger'),
  in_tender: r('in_tender', 'В тендере', 'progress'),
  handed_over: r('handed_over', 'Передана в БЗО', 'success'),
  closed: r('closed', 'Закрыта', 'muted'),
  cancelled: r('cancelled', 'Отменена', 'muted'),
};

const tn = dictionary('tender');
export const TENDER_STATUSES: Record<string, StatusDef> = {
  draft: tn('draft', 'Черновик', 'draft'),
  intake: tn('intake', 'Приём предложений', 'progress'),
  opened: tn('opened', 'Вскрыт', 'progress'),
  on_approval: tn('on_approval', 'На утверждении', 'progress'),
  awarded: tn('awarded', 'Выбор утверждён', 'success'),
  handed_over: tn('handed_over', 'Документы в БЗО', 'success'),
  delivery: tn('delivery', 'Поставка', 'progress'),
  closed: tn('closed', 'Закрыт', 'muted'),
  cancelled: tn('cancelled', 'Отменён', 'muted'),
  failed: tn('failed', 'Не состоялся', 'danger'),
  rework: tn('rework', 'Возвращён на доработку', 'attention'),
};

const inv = dictionary('invitation');
export const INVITATION_STATUSES: Record<string, StatusDef> = {
  created: inv('created', 'Ссылка не выпущена', 'draft'),
  sent: inv('sent', 'Отправлено', 'progress'),
  delivery_error: inv('delivery_error', 'Ошибка доставки', 'danger'),
  opened: inv('opened', 'Открыто', 'progress'),
  submitted: inv('submitted', 'Подано', 'success'),
  declined: inv('declined', 'Отказался', 'muted'),
  awarded: inv('awarded', 'Победитель', 'success'),
  not_awarded: inv('not_awarded', 'Не выбран', 'muted'),
  revoked: inv('revoked', 'Отозвано', 'muted'),
  expired: inv('expired', 'Срок истёк', 'muted'),
};

export const STATUS_DICTIONARIES = {
  request: TENDER_REQUEST_STATUSES,
  tender: TENDER_STATUSES,
  invitation: INVITATION_STATUSES,
};

export type TenderStatusKind = keyof typeof STATUS_DICTIONARIES;

export const TONE_CLASS: Record<StatusTone, string> = {
  draft: 'border-transparent bg-secondary text-secondary-foreground',
  progress: 'border-transparent bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-200',
  attention: 'border-transparent bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200',
  success: 'border-transparent bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200',
  danger: 'border-transparent bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200',
  muted: 'border-transparent bg-muted text-muted-foreground',
};
