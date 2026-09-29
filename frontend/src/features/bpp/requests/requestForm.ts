/**
 * Состояние формы F-02 «Заявка на закупку» и её правила (ТЗ §7.3–7.6) —
 * отдельно от экрана, чтобы проверять без рендера.
 *
 * - сумма позиции — CALC-004 `ROUND(Кол-во × Цена, 2)`, в копейках без
 *   `float`; сумма заявки — Σ позиций;
 * - «Остаток после заявки» = доступный остаток статьи − сумма заявки, пока
 *   заявка не в резерве (ТЗ §7.3); < 0 — отправка закрыта (§7.6 п.4);
 * - вставка позиций из буфера (Excel: Наименование / Ед. / Кол-во / Цена,
 *   ТЗ §7.4 [Л]) — строки таблицы, единица ищется по краткому имени или коду.
 */
import { formatMoney, parseMoneyInput } from '../format';
import { fromCents, lessThan, subMoney, sumMoney, toCents } from '../budgets/cents';

import type {
  InitiatorRole, PurchaseRequestCard, PurchaseType, RequestInput,
} from './api';

export const MAX_ITEMS = 200;
/** Роль инициатора коротко — колонка «Роль» реестра L-02. */
export const ROLE_LABELS: Record<string, string> = { sn: 'СН', pm: 'ПМ' };
export const JUSTIFICATION_MIN = 10;

export interface EditItem {
  key: string;
  sys_number: string | null;
  name: string;
  specs: string;
  uom_id: string;
  qty: string;
  price: string;
  need_date: string;
}

export interface RequestFormState {
  initiator_role: InitiatorRole | '';
  project_id: string;
  article_id: string;
  purchase_type: PurchaseType;
  need_date: string;
  justification: string;
  items: EditItem[];
}

let itemSeq = 0;
export const nextItemKey = () => `item-${(itemSeq += 1)}`;

export function emptyItem(needDate: string, uomId = ''): EditItem {
  return {
    key: nextItemKey(), sys_number: null, name: '', specs: '', uom_id: uomId, qty: '',
    price: '', need_date: needDate,
  };
}

/** Количество — до трёх знаков после запятой (decimal(15,3), ТЗ §7.4). */
export function parseQtyInput(text: string): string | null {
  const compact = text.replace(/[\s\u00a0\u202f]/g, '').replace(',', '.');
  const match = /^(\d*)(?:\.(\d*))?$/.exec(compact);
  if (!match) return null;
  const [, whole = '', frac = ''] = match;
  if ((!whole && !frac) || frac.length > 3) return null;
  return `${(whole || '0').replace(/^0+(?=\d)/, '')}.${frac.padEnd(3, '0')}`;
}

/** CALC-004: `ROUND(qty × price, 2)` по правилу «половина — вверх». */
export function lineAmount(qty: string, price: string): string | null {
  const q = parseQtyInput(qty);
  const p = parseMoneyInput(price);
  if (q === null || p === null) return null;
  const milli = BigInt(q.replace('.', ''));        // кол-во × 1000
  const cents = toCents(p) ?? 0n;                  // цена × 100
  const product = milli * cents;                   // × 100 000
  const rounded = (product + 500n) / 1000n;        // → копейки
  return fromCents(rounded);
}

export function totalAmount(items: EditItem[]): string {
  return sumMoney(items.map((item) => lineAmount(item.qty, item.price)));
}

/** «Остаток после заявки»: `null` — статья не выбрана или остатка нет. */
export function afterRequest(available: string | null | undefined, total: string,
  reserved: boolean): string | null {
  if (available === null || available === undefined) return null;
  return reserved ? available : subMoney(available, total);
}

export function formOf(card: PurchaseRequestCard | undefined, role: InitiatorRole | ''): RequestFormState {
  if (!card) {
    return {
      initiator_role: role, project_id: '', article_id: '', purchase_type: '',
      need_date: '', justification: '', items: [],
    };
  }
  return {
    initiator_role: card.initiator_role,
    project_id: card.project.id,
    article_id: card.article?.id ?? '',
    purchase_type: card.purchase_type,
    need_date: card.need_date ?? '',
    justification: card.justification,
    items: card.items.map((item) => ({
      key: nextItemKey(), sys_number: item.sys_number, name: item.name, specs: item.specs,
      uom_id: item.uom_id, qty: item.qty.replace('.', ','), price: formatMoney(item.price),
      need_date: item.need_date,
    })),
  };
}

export function requestInput(form: RequestFormState): RequestInput {
  return {
    initiator_role: form.initiator_role || null,
    project_id: form.project_id || null,
    article_id: form.article_id || null,
    purchase_type: form.purchase_type,
    need_date: form.need_date || null,
    justification: form.justification.trim(),
    items: form.items.map((item) => ({
      name: item.name.trim(),
      specs: item.specs.trim(),
      uom_id: item.uom_id || null,
      qty: parseQtyInput(item.qty) ?? '0',
      price: parseMoneyInput(item.price) ?? '0',
      need_date: item.need_date || null,
    })),
  };
}

/**
 * Проверки перед «Отправить на согласование» (ТЗ §7.3–7.4, §13.2): ключ —
 * поле (`project_id`, …) или `item:<key>`; пустой объект — можно отправлять.
 * «Сохранить черновик» требует только проект (ТЗ §7.7).
 */
export function submitErrors(form: RequestFormState, today: string): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!form.initiator_role) errors.initiator_role = 'Выберите роль инициатора';
  if (!form.project_id) errors.project_id = 'Выберите проект';
  if (!form.article_id) errors.article_id = 'Выберите статью бюджета';
  if (!form.purchase_type) errors.purchase_type = 'Выберите вид закупки';
  if (!form.need_date) errors.need_date = 'Укажите дату потребности';
  else if (form.need_date < today) errors.need_date = 'Дата потребности — не раньше сегодняшней';
  const justification = form.justification.trim().length;
  if (justification < JUSTIFICATION_MIN) {
    errors.justification = `Обоснование — не короче ${JUSTIFICATION_MIN} символов`;
  }
  if (form.items.length === 0) errors.items = 'Добавьте хотя бы одну позицию';
  if (form.items.length > MAX_ITEMS) errors.items = `Не больше ${MAX_ITEMS} позиций в заявке`;
  for (const item of form.items) {
    const name = item.name.trim().length;
    const qty = parseQtyInput(item.qty);
    const price = parseMoneyInput(item.price);
    let problem: string | null = null;
    if (name < 3) problem = 'Наименование — от 3 символов';
    else if (!item.uom_id) problem = 'Выберите единицу измерения';
    else if (qty === null || BigInt(qty.replace('.', '')) <= 0n) problem = 'Количество — больше нуля';
    else if (price === null || !lessThan('0', price)) problem = 'Цена — больше нуля';
    else if (!item.need_date || item.need_date < today) problem = 'Дата потребности — не раньше сегодняшней';
    if (problem) errors[`item:${item.key}`] = problem;
  }
  return errors;
}

export interface Uom { id: string; code: string; short_name: string }

/**
 * Позиции из буфера обмена (Excel/Google Sheets): строки через перевод
 * строки, колонки через табуляцию — Наименование, Ед., Кол-во, Цена.
 * Строка-заголовок («Наименование…») пропускается. Нераспознанная единица —
 * пустая (форма подсветит), число — как есть (форма проверит формат).
 */
export function parsePastedItems(text: string, uoms: Uom[], needDate: string): EditItem[] {
  const byName = new Map<string, string>();
  for (const uom of uoms) {
    byName.set(uom.short_name.trim().toLowerCase(), uom.id);
    byName.set(uom.code.trim().toLowerCase(), uom.id);
  }
  return text
    .split(/\r?\n/)
    .map((line) => line.split('\t').map((cell) => cell.trim()))
    .filter((cells) => cells.some(Boolean))
    .filter((cells) => !/^наименование/i.test(cells[0] ?? ''))
    .map(([name = '', uom = '', qty = '', price = '']) => ({
      ...emptyItem(needDate),
      name,
      uom_id: byName.get(uom.toLowerCase()) ?? '',
      qty,
      price,
    }));
}
