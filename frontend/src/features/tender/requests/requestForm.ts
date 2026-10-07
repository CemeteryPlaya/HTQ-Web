/**
 * Состояние формы заявки на тендер и её правила (T1.4; план этапов 0–2
 * §3.1–3.2) — отдельно от экрана, чтобы проверять без рендера.
 *
 * - Позиция без своей статьи идёт по статье заявки; доставка и СМР — по
 *   своим статьям с плановой суммой. По этой же группировке сервер режет
 *   заявку на части (ЗЗ БЗО), поэтому подсказка остатка в форме считает
 *   плановую сумму на статью так же (`planByArticle`).
 * - Сумма позиции — `ROUND(Кол-во × Плановая цена, 2)` в копейках, без
 *   `float` (`lineAmount` формы заявки БЗО).
 * - Проверки перед отправкой повторяют серверные (T-04 — плановая сумма
 *   доставки и СМР > 0, T-05 — обоснование от 10 символов); сервер всё
 *   равно проверит сам.
 */
import { lessThan, sumMoney } from '@/features/bpp/budgets/cents';
import { formatMoney, parseMoneyInput } from '@/features/bpp/format';
import { lineAmount, parseQtyInput } from '@/features/bpp/requests/requestForm';

import type {
  InitiatorRole, PurchaseType, TenderRequestCard, TenderRequestInput,
} from './api';

export const MAX_ITEMS = 200;
export const JUSTIFICATION_MIN = 10;
export const COMMENT_MIN = 10;

export interface EditItem {
  key: string;
  /** Ключ позиции на сервере; `null` — новая строка (в т.ч. копия). */
  id: string | null;
  name: string;
  specs: string;
  uom_id: string;
  qty: string;
  plan_price: string;
  need_date: string;
  /** `''` — по статье заявки. */
  article_id: string;
}

export interface TenderRequestForm {
  initiator_role: InitiatorRole | '';
  project_id: string;
  article_id: string;
  purchase_type: PurchaseType;
  need_date: string;
  delivery_address: string;
  justification: string;
  needs_delivery: boolean;
  delivery_article_id: string;
  delivery_plan_amount: string;
  needs_works: boolean;
  works_scope: string;
  works_article_id: string;
  works_plan_amount: string;
  allow_analogs: boolean;
  allow_partial: boolean;
  items: EditItem[];
}

let itemSeq = 0;
export const nextItemKey = () => `tender-item-${(itemSeq += 1)}`;

export function emptyItem(needDate: string, uomId = ''): EditItem {
  return {
    key: nextItemKey(), id: null, name: '', specs: '', uom_id: uomId, qty: '', plan_price: '',
    need_date: needDate, article_id: '',
  };
}

const moneyText = (value: string | null) => (value ? formatMoney(value) : '');

export function formOf(card: TenderRequestCard | undefined, role: InitiatorRole | ''): TenderRequestForm {
  if (!card) {
    return {
      initiator_role: role, project_id: '', article_id: '', purchase_type: 'goods', need_date: '',
      delivery_address: '', justification: '', needs_delivery: false, delivery_article_id: '',
      delivery_plan_amount: '', needs_works: false, works_scope: '', works_article_id: '',
      works_plan_amount: '', allow_analogs: false, allow_partial: true, items: [],
    };
  }
  return {
    initiator_role: card.initiator_role,
    project_id: card.project_id,
    article_id: card.article_id ?? '',
    purchase_type: card.purchase_type,
    need_date: card.need_date ?? '',
    delivery_address: card.delivery_address,
    justification: card.justification,
    needs_delivery: card.needs_delivery,
    delivery_article_id: card.delivery_article_id ?? '',
    delivery_plan_amount: moneyText(card.delivery_plan_amount),
    needs_works: card.needs_works,
    works_scope: card.works_scope,
    works_article_id: card.works_article_id ?? '',
    works_plan_amount: moneyText(card.works_plan_amount),
    allow_analogs: card.allow_analogs,
    allow_partial: card.allow_partial,
    items: card.items.map((item) => ({
      key: nextItemKey(), id: item.id, name: item.name, specs: item.specs, uom_id: item.uom_id,
      qty: item.qty.replace('.', ','), plan_price: formatMoney(item.plan_price),
      need_date: item.need_date, article_id: item.article_id ?? '',
    })),
  };
}

export function requestInput(form: TenderRequestForm): TenderRequestInput {
  const delivery = form.needs_delivery;
  const works = form.needs_works;
  return {
    initiator_role: form.initiator_role || null,
    project_id: form.project_id || null,
    article_id: form.article_id || null,
    purchase_type: form.purchase_type,
    need_date: form.need_date || null,
    delivery_address: form.delivery_address.trim(),
    justification: form.justification.trim(),
    needs_delivery: delivery,
    delivery_article_id: delivery ? form.delivery_article_id || null : null,
    delivery_plan_amount: delivery ? parseMoneyInput(form.delivery_plan_amount) : null,
    needs_works: works,
    works_scope: works ? form.works_scope.trim() : '',
    works_article_id: works ? form.works_article_id || null : null,
    works_plan_amount: works ? parseMoneyInput(form.works_plan_amount) : null,
    allow_analogs: form.allow_analogs,
    allow_partial: form.allow_partial,
    items: form.items.map((item) => ({
      id: item.id,
      name: item.name.trim(),
      specs: item.specs.trim(),
      uom_id: item.uom_id || null,
      // Нечисло — `null`: сервер ответит по полю «нужно число больше нуля».
      qty: parseQtyInput(item.qty),
      plan_price: parseMoneyInput(item.plan_price),
      need_date: item.need_date || null,
      article_id: item.article_id || null,
    })),
  };
}

const positive = (text: string) => {
  const value = parseMoneyInput(text);
  return value !== null && lessThan('0', value);
};

/**
 * Проверки перед «Отправить на согласование»: ключ — поле формы или
 * `item:<key>`; пустой объект — можно отправлять. Тексты — для человека.
 */
export function submitErrors(form: TenderRequestForm, today: string): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!form.initiator_role) errors.initiator_role = 'Выберите роль инициатора';
  if (!form.project_id) errors.project_id = 'Выберите проект';
  if (!form.article_id && form.items.some((item) => !item.article_id)) {
    errors.article_id = 'Выберите статью бюджета — по ней пойдут позиции без своей статьи';
  }
  if (!form.need_date) errors.need_date = 'Укажите дату потребности';
  else if (form.need_date < today) errors.need_date = 'Дата потребности — не раньше сегодняшней';
  if (form.justification.trim().length < JUSTIFICATION_MIN) {
    errors.justification = `Обоснование — не короче ${JUSTIFICATION_MIN} символов`;
  }
  if (form.needs_delivery) {
    if (!form.delivery_article_id) errors.delivery_article_id = 'Выберите статью доставки';
    if (!positive(form.delivery_plan_amount)) {
      errors.delivery_plan_amount = 'Плановая сумма доставки — больше нуля';
    }
  }
  if (form.needs_works) {
    if (!form.works_scope.trim()) errors.works_scope = 'Опишите объём работ';
    if (!form.works_article_id) errors.works_article_id = 'Выберите статью СМР';
    if (!positive(form.works_plan_amount)) errors.works_plan_amount = 'Плановая сумма СМР — больше нуля';
  }
  if (form.items.length === 0) errors.items = 'Добавьте хотя бы одну позицию';
  if (form.items.length > MAX_ITEMS) errors.items = `Не больше ${MAX_ITEMS} позиций в заявке`;
  for (const item of form.items) {
    const qty = parseQtyInput(item.qty);
    let problem: string | null = null;
    if (item.name.trim().length < 3) problem = 'Наименование — от 3 символов';
    else if (!item.uom_id) problem = 'Выберите единицу измерения';
    else if (qty === null || BigInt(qty.replace('.', '')) <= 0n) problem = 'Количество — больше нуля';
    else if (!positive(item.plan_price)) problem = 'Цена — больше нуля';
    else if (!item.need_date || item.need_date < today) problem = 'Дата потребности — не раньше сегодняшней';
    if (problem) errors[`item:${item.key}`] = problem;
  }
  return errors;
}

/** Плановая сумма позиции или `null`, если количество или цена не числа. */
export const itemAmount = (item: EditItem): string | null => lineAmount(item.qty, item.plan_price);

/** Сумма основных позиций. */
export const itemsTotal = (items: EditItem[]): string => sumMoney(items.map(itemAmount));

/**
 * Плановая сумма по статьям — как сервер группирует позиции в части:
 * позиция — по своей статье или статье заявки, доставка и СМР — по своим.
 * Порядок ключей — порядок появления в форме.
 */
export function planByArticle(form: TenderRequestForm): Map<string, string> {
  const plan = new Map<string, string>();
  const add = (articleId: string, amount: string | null) => {
    if (!articleId || amount === null) return;
    plan.set(articleId, sumMoney([plan.get(articleId) ?? '0', amount]));
  };
  for (const item of form.items) add(item.article_id || form.article_id, itemAmount(item));
  if (form.needs_delivery) {
    add(form.delivery_article_id, parseMoneyInput(form.delivery_plan_amount));
  }
  if (form.needs_works) add(form.works_article_id, parseMoneyInput(form.works_plan_amount));
  return plan;
}
