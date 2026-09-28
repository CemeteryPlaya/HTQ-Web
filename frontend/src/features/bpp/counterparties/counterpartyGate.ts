/**
 * Можно ли ставить контрагента в новый документ этапа 3 (договор, счёт) и
 * нужно ли подтверждение автора (D-20, ТЗ §18) — то же правило, что у
 * сервера (`services/counterparties/lookup.py`: `assert_usable`,
 * `needs_confirmation`):
 *
 * - `unusable` — заблокирован или в архиве: документ с ним не отправить
 *   (сервер ответит E-CTR-01);
 * - `confirm` — действующий, но без метки «Проверенный»: автор
 *   подтверждает выбор в окне, подтверждение пишется в аудит документа;
 * - `ok` — проверенный и действующий: окна нет.
 *
 * Вход — поля `lookup.brief` / строки реестра; лишние поля не мешают.
 */
export interface CounterpartyForConfirm {
  id: string;
  name: string;
  short_name?: string;
  status: string;
  is_verified: boolean;
  block_reason?: string;
  blocked_at?: string | null;
  successful_documents?: number;
  verified_threshold?: number;
}

export type CounterpartyGate = 'ok' | 'confirm' | 'unusable';

export function counterpartyGate(counterparty: CounterpartyForConfirm): CounterpartyGate {
  if (counterparty.status !== 'active') return 'unusable';
  return counterparty.is_verified ? 'ok' : 'confirm';
}

export const counterpartyDisplayName = (counterparty: CounterpartyForConfirm): string =>
  counterparty.short_name || counterparty.name;
