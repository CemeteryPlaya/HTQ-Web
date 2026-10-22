/**
 * Желаемая схема оплаты тендера (план §4.1): шаблоны 1–3 —
 * 1 предоплата 100 %; 2 аванс X % до отгрузки + остаток по приёмке;
 * 3 постоплата через N дней после приёмки. Этапы строит сервер по шаблону
 * (`PUT payment-scheme {kind, advance_pct?, postpay_days?}`); здесь —
 * ввод, его проверка и подпись уже сохранённой схемы. Схема 4 («по
 * этапам») — после пилота.
 */
import type { PaymentScheme, SchemeInput, SchemeKind } from './api';

export interface SchemeDraft {
  kind: SchemeKind | '';
  advance_pct: string;
  postpay_days: string;
}

type Translate = (key: string, fallback: string, options?: Record<string, unknown>) => string;

/** Без i18n — запасной текст с подстановкой `{{name}}`. */
const plain: Translate = (_key, fallback, options) =>
  fallback.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(options?.[name] ?? ''));

const PCT = /^\d{1,2}([.,]\d{1,2})?$/;
const DAYS = /^\d{1,3}$/;
export const MAX_POSTPAY_DAYS = 365;

const pctOf = (text: string) => text.trim().replace(',', '.');
const trimZeros = (pct: string) => pct.replace(/\.0+$/, '').replace(/(\.\d*?)0+$/, '$1');

export function schemeErrors(draft: SchemeDraft, t: Translate = plain): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!draft.kind) {
    errors.kind = t('tender.tenders.schemeRequired', 'Выберите схему оплаты');
  } else if (draft.kind === 'advance') {
    const pct = pctOf(draft.advance_pct);
    const value = Number(pct);
    if (!PCT.test(draft.advance_pct.trim()) || value < 1 || value > 99) {
      errors.advance_pct = t('tender.tenders.advanceRange', 'Аванс — от 1 до 99 %');
    }
  } else if (draft.kind === 'postpay') {
    const days = draft.postpay_days.trim();
    if (!DAYS.test(days) || Number(days) < 1 || Number(days) > MAX_POSTPAY_DAYS) {
      errors.postpay_days = t('tender.tenders.postpayRange', 'Отсрочка — целое число дней от 1 до {{max}}', {
        max: MAX_POSTPAY_DAYS,
      });
    }
  }
  return errors;
}

export function schemeInput(draft: SchemeDraft): SchemeInput {
  if (draft.kind === 'advance') return { kind: 'advance', advance_pct: pctOf(draft.advance_pct) };
  if (draft.kind === 'postpay') return { kind: 'postpay', postpay_days: Number(draft.postpay_days.trim()) };
  return { kind: 'prepay' };
}

export function schemeDraftOf(scheme: PaymentScheme | null): SchemeDraft {
  if (!scheme) return { kind: '', advance_pct: '', postpay_days: '' };
  const kind = (['prepay', 'advance', 'postpay'] as const).find((value) => value === scheme.kind) ?? '';
  const advance = kind === 'advance' ? scheme.stages.find((stage) => stage.order === 1) : undefined;
  return {
    kind,
    advance_pct: advance ? trimZeros(advance.pct) : '',
    postpay_days: kind === 'postpay' && scheme.postpay_days !== null ? String(scheme.postpay_days) : '',
  };
}

/** Подпись сохранённой схемы — по её этапам. */
export function describeScheme(scheme: PaymentScheme | null, t: Translate = plain): string {
  if (!scheme) return t('tender.tenders.schemeNone', 'Не задана');
  if (scheme.kind === 'prepay') return t('tender.tenders.schemePrepayText', 'Предоплата 100 %');
  if (scheme.kind === 'postpay') {
    return t('tender.tenders.schemePostpayText', 'Постоплата через {{days}} дн. после приёмки', {
      days: scheme.postpay_days ?? '—',
    });
  }
  if (scheme.kind === 'advance') {
    const sorted = [...scheme.stages].sort((a, b) => a.order - b.order);
    const [first, second] = sorted;
    return t('tender.tenders.schemeAdvanceText', 'Аванс {{advance}} % до отгрузки, {{rest}} % по приёмке', {
      advance: first ? trimZeros(first.pct) : '—',
      rest: second ? trimZeros(second.pct) : '—',
    });
  }
  return String(scheme.kind);
}
