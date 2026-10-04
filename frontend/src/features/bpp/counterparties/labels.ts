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

/**
 * Подписи полей журнала изменений карточки (вкладка «История изменений»):
 * поля карточки (`EDITABLE_FIELDS` сервера), статуса и метки, а также
 * банковских счетов (`account_added`/`account_updated` пишут их в журнал
 * контрагента). Названия — те же, что в форме и на панели счетов.
 */
export const historyFieldLabels = (t: TFunction, countryCode: string): Record<string, string> => ({
  name: t('bpp.counterparties.name', 'Наименование'),
  short_name: t('bpp.counterparties.shortName', 'Краткое наименование'),
  kind: t('bpp.counterparties.kindTitle', 'Тип'),
  country_code: t('bpp.counterparties.country', 'Страна'),
  reg_number: regNumberLabel(t, countryCode),
  is_vat_payer: t('bpp.counterparties.vatPayer', 'Плательщик НДС'),
  vat_cert_series: t('bpp.counterparties.vatSeries', 'Серия свидетельства НДС'),
  vat_cert_number: t('bpp.counterparties.vatNumber', 'Номер свидетельства НДС'),
  legal_address: t('bpp.counterparties.legalAddress', 'Юридический адрес'),
  contact_person: t('bpp.counterparties.contactPerson', 'Контактное лицо'),
  phone: t('bpp.counterparties.phone', 'Телефон'),
  email: t('bpp.counterparties.email', 'E-mail'),
  ext_1c_ref: t('bpp.counterparties.ext1c', 'Код в 1С'),
  status: t('bpp.counterparties.statusTitle', 'Статус'),
  block_reason: t('bpp.counterparties.blockReason', 'Причина блокировки'),
  verified_override: t('bpp.counterparties.verifiedControl', 'Метка «Проверенный»'),
  account_id: t('bpp.counterparties.accountId', 'Банковский счёт'),
  iban: 'IBAN',
  bank_name: t('bpp.counterparties.bank', 'Банк'),
  bic: t('bpp.counterparties.bic', 'БИК'),
  currency: t('bpp.counterparties.currency', 'Валюта'),
  is_primary: t('bpp.counterparties.primaryAccount', 'Основной счёт'),
  is_active: t('bpp.counterparties.accountActive', 'Действующий счёт'),
});
