/**
 * Сравнение предложений и выбор поставщиков (этап 5; ручки
 * `tenders/<id>/comparison`, `…/award`; спека этапа 5, §3 T5.1–T5.2).
 *
 * Деньги приходят строками (`Decimal` сервера) и здесь не пересчитываются:
 * «самый дешёвый», итоги и экономию считает сервер (`cheapest_invitation_id`,
 * `total_*_kzt`, `saving_common_kzt`). Сумма в KZT `null` — нет курса на дату
 * вскрытия (предупреждение `no_rate`).
 */
import type { PaymentScheme } from './api';

export interface OfferFile {
  id: string;
  name: string;
  size: number;
}

export interface ComparisonSupplier {
  invitation_id: string;
  name: string;
  counterparty_id: string | null;
  prospect_id: string | null;
  offer_id: string;
  offer_number: string | null;
  currency_code: string;
  rate: string | null;
  rate_on: string | null;
  with_vat: boolean;
  vat_rate: string | null;
  valid_until: string | null;
  valid_expired: boolean;
  payment_scheme: PaymentScheme | null;
  coverage: { offered: number; total: number };
  total_common_kzt: string | null;
  total_full_kzt: string | null;
  saving_common_kzt: string | null;
  files: OfferFile[];
  requisites: Record<string, string>;
  extra_terms: string;
}

export interface ItemOfferCell {
  participates: boolean;
  line_id?: string;
  price?: string;
  qty?: string;
  partial_qty?: boolean;
  amount?: string;
  amount_kzt?: string | null;
  unit_price_kzt?: string | null;
  delivery_date?: string | null;
  is_analog?: boolean;
  analog_note?: string;
  comment?: string;
}

export interface ComparisonItem {
  item_id: string;
  line_no: number;
  name: string;
  specs: string;
  uom: { code: string; short_name: string };
  qty: string;
  plan_price: string;
  plan_amount: string;
  in_common_set: boolean;
  offers: Record<string, ItemOfferCell>;
  cheapest_invitation_id: string | null;
}

export type ExtraKind = 'delivery' | 'works';

export interface ExtraOfferCell {
  extra_id: string;
  included_in_price: boolean;
  amount: string;
  amount_kzt: string | null;
  note: string;
}

export interface ComparisonExtra {
  kind: ExtraKind | string;
  plan_amount: string | null;
  offers: Record<string, ExtraOfferCell | null>;
  cheapest_invitation_id: string | null;
}

export type ComparisonWarning =
  | { code: 'no_rate'; invitation_id: string; currency_code: string }
  | { code: 'valid_expired'; invitation_id: string; valid_until: string };

export interface Comparison {
  tender_id: string;
  rate_date: string;
  opened_at: string;
  suppliers: ComparisonSupplier[];
  items: ComparisonItem[];
  extras: ComparisonExtra[];
  totals: { declined: { invitation_id: string; name: string; reason: string }[]; suppliers: number };
  warnings: ComparisonWarning[];
}

// ── выбор ───────────────────────────────────────────────────────────────

interface AwardBase {
  award_id: string;
  invitation_id: string;
  supplier: string;
  part_id: string;
  qty: string;
  amount: string;
  currency_code: string;
  amount_kzt: string | null;
  plan_amount_kzt: string;
  is_cheapest: boolean;
  comment: string;
}

export interface AwardLine extends AwardBase {
  line_id: string;
  item_id: string;
  line_no: number;
  name: string;
  price: string;
  is_analog: boolean;
}

export interface AwardExtra extends AwardBase {
  extra_id: string;
  kind: ExtraKind | string;
  included_in_price: boolean;
}

export interface AwardView {
  tender_id: string;
  version: number;
  status: string;
  comment: string;
  status_comment: string;
  lines: AwardLine[];
  extras: AwardExtra[];
  suppliers: { invitation_id: string; name: string; currency_code: string; amount: string; amount_kzt: string | null }[];
  parts: { part_id: string; kind: string; article_id: string; plan_kzt: string; amount_kzt: string; over_plan_kzt: string }[];
  allowed_actions: string[];
}

export interface AwardInput {
  version: number;
  comment: string;
  lines: { line_id: string; qty?: string; comment?: string }[];
  extras: { extra_id: string; comment?: string }[];
}

/** Дефицит бюджета статьи (422 `E-TND-11`, `details.deficits`). */
export interface Deficit {
  article_id: string;
  article_code: string;
  over: string;
  available: string;
}

/** Что выбрано в строке формы выбора. */
export interface LineChoice {
  invitationId: string;
  qty: string;
  comment: string;
}

/** Строка отказа `E-TND-12` (`details.rows`): позиция или доставка/СМР. */
export type MissingRow = { line_id: string; item_id: string } | { extra_id: string; kind: string };

/** Минимум символов комментария к выбору не самого дешёвого (S5-07). */
export const AWARD_COMMENT_MIN = 10;

/** Состояние формы выбора из сохранённого выбора. */
export function choicesOf(view: AwardView | undefined): {
  lines: Record<string, LineChoice>;
  extras: Record<string, { invitationId: string; comment: string }>;
  comment: string;
} {
  const lines: Record<string, LineChoice> = {};
  const extras: Record<string, { invitationId: string; comment: string }> = {};
  for (const row of view?.lines ?? []) {
    lines[row.item_id] = { invitationId: row.invitation_id, qty: row.qty, comment: row.comment };
  }
  for (const row of view?.extras ?? []) {
    if (!row.included_in_price) extras[row.kind] = { invitationId: row.invitation_id, comment: row.comment };
  }
  return { lines, extras, comment: view?.comment ?? '' };
}

/** Победители — поставщики хотя бы одной выбранной позиции (S5-06). */
export function winnersOf(lines: Record<string, LineChoice>): Set<string> {
  return new Set(Object.values(lines).map((row) => row.invitationId).filter(Boolean));
}

/**
 * Тело `PUT award` и ключи его строк: `lineKeys[i]` — позиция строки
 * `lines[i]`, `extraKeys[j]` — вид доставки/СМР строки `extras[j]` (ошибки
 * сервера адресуют строки индексом: `lines[2].comment`).
 *
 * Доставка и СМР «в цене» у победителя сервер выбирает сам — в тело они не
 * идут; выбранная строка доставки у поставщика, который перестал быть
 * победителем, отбрасывается.
 */
export function awardInput(
  data: Comparison,
  choice: ReturnType<typeof choicesOf>,
  version: number,
): { body: AwardInput; lineKeys: string[]; extraKeys: string[] } {
  const winners = winnersOf(choice.lines);
  const lines: AwardInput['lines'] = [];
  const lineKeys: string[] = [];
  for (const item of data.items) {
    const row = choice.lines[item.item_id];
    const cell = row ? item.offers[row.invitationId] : undefined;
    if (!row || !cell?.line_id) continue;
    const qty = row.qty.trim();
    lines.push({
      line_id: cell.line_id,
      ...(qty && qty !== cell.qty ? { qty } : {}),
      ...(row.comment.trim() ? { comment: row.comment.trim() } : {}),
    });
    lineKeys.push(item.item_id);
  }
  const extras: AwardInput['extras'] = [];
  const extraKeys: string[] = [];
  for (const extra of data.extras) {
    const row = choice.extras[extra.kind];
    const cell = row ? extra.offers[row.invitationId] : null;
    if (!row || !cell || cell.included_in_price || !winners.has(row.invitationId)) continue;
    extras.push({ extra_id: cell.extra_id, ...(row.comment.trim() ? { comment: row.comment.trim() } : {}) });
    extraKeys.push(extra.kind);
  }
  return { body: { version, comment: choice.comment.trim(), lines, extras }, lineKeys, extraKeys };
}

/** Ошибки сервера по строкам (`lines[i].x`, `extras[j].x`) — к ключам строк формы. */
export function rowErrors(
  fields: Record<string, string>,
  lineKeys: string[],
  extraKeys: string[],
): RowErrors {
  const lines: RowErrors['lines'] = {};
  const extras: RowErrors['extras'] = {};
  const rest: Record<string, string> = {};
  for (const [field, message] of Object.entries(fields)) {
    const line = /^lines\[(\d+)\]\.?(\w*)/.exec(field);
    const extra = /^extras\[(\d+)\]\.?(\w*)/.exec(field);
    const lineKey = line ? lineKeys[Number(line[1])] : undefined;
    const extraKey = extra ? extraKeys[Number(extra[1])] : undefined;
    if (line && lineKey) (lines[lineKey] ??= {})[line[2] || 'line_id'] ??= message;
    else if (extra && extraKey) (extras[extraKey] ??= {})[extra[2] || 'extra_id'] ??= message;
    else rest[field] = message;
  }
  return { lines, extras, rest };
}

/** Ошибки строк по полю: `lines[key].qty`, `lines[key].comment`, `lines[key].line_id`. */
export interface RowErrors {
  lines: Record<string, Record<string, string>>;
  extras: Record<string, Record<string, string>>;
  rest: Record<string, string>;
}

/** Строка выбрана не у самого дешёвого — нужен комментарий строки. */
export function needsLineComment(item: ComparisonItem, invitationId: string): boolean {
  return Boolean(invitationId) && item.cheapest_invitation_id !== null
    && item.cheapest_invitation_id !== invitationId;
}
