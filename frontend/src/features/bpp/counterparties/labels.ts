/**
 * Подписи справочника «Контрагенты»: тип контрагента (`CounterpartyKind`
 * сервера) и статус для фильтра реестра. Бейдж статуса — общий словарь
 * `core/statusDictionaries.ts` (вид `counterparty`), здесь только пункты
 * выпадающего фильтра.
 */
import type { TFunction } from 'i18next';

import type { CounterpartyKind, CounterpartyStatus } from './api';

export const KIND_LABELS: Record<CounterpartyKind, [string, string]> = {
  legal: ['bpp.counterparties.kind.legal', 'Юридическое лицо'],
  ip: ['bpp.counterparties.kind.ip', 'Индивидуальный предприниматель'],
  individual: ['bpp.counterparties.kind.individual', 'Физическое лицо'],
  nonresident: ['bpp.counterparties.kind.nonresident', 'Нерезидент'],
};

export const KINDS = Object.keys(KIND_LABELS) as CounterpartyKind[];

export const kindLabel = (t: TFunction, kind: string): string => {
  const known = KIND_LABELS[kind as CounterpartyKind];
  return known ? t(known[0], known[1]) : kind;
};

export const STATUS_OPTIONS: Record<CounterpartyStatus, [string, string]> = {
  active: ['bpp.status.counterparty.active', 'Активен'],
  blocked: ['bpp.status.counterparty.blocked', 'Заблокирован'],
  archived: ['bpp.status.counterparty.archived', 'Архив'],
};

/** Номер у казахстанского контрагента — БИН/ИИН, у прочих — рег. номер. */
export const regNumberLabel = (t: TFunction, countryCode: string): string =>
  countryCode.toUpperCase() === 'KZ'
    ? t('bpp.counterparties.binIin', 'БИН/ИИН')
    : t('bpp.counterparties.regNumber', 'Регистрационный номер');
