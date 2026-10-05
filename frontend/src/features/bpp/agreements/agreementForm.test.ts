/**
 * Правила формы F-04 (ТЗ §9.2–9.3): обязательные поля, Σ позиций = сумме
 * (BR-033), количество ≤ остатка (BR-042), превышение над планом (BR-034),
 * ручная ставка НДС уходит только если её правили (D-14).
 */
import { describe, expect, it } from 'vitest';

import { proportionalAmount } from '../plan/planSelection';

import type { AgreementCard } from './api';
import { formOf, overPlan, patchOf, submitErrors } from './agreementForm';

const card = (over: Partial<AgreementCard> = {}): AgreementCard => ({
  id: 'a1', number: 'ДГ-2026-000001', status: 'draft', version: 2, author_id: 904,
  author_name: 'Иванов А.', created_at: '2026-09-28T05:00:00Z',
  project: { id: 'p1', code: 'П-015', name: 'Объект' },
  article: { id: 'art', code: 'T-METAL', name: 'Металлопрокат', archived: false },
  counterparty: {
    id: 'c1', name: 'ТОО «Альфа»', short_name: '', reg_number: '100000000001',
    country_code: 'KZ', is_vat_payer: true, status: 'active', is_verified: true,
  },
  counterparty_confirmed: false, name: 'Договор на ТМЦ по проекту П-015', ext_number: '145',
  ext_date: '2026-09-28', agreement_type: 'goods', is_open: false, amount: '1500.00',
  currency_code: 'KZT', with_vat: true, vat_rate: '16.00', vat_source: 'refdata',
  vat_amount: '206.90', amount_without_vat: '1293.10', vat_warning: null, valid_to: null,
  status_comment: '', rework_comment: '', parent: null, supplements: [],
  effective_amount: '1500.00', remaining: null,
  budget: { available: '300.00', over_plan: '0.00', plan_total: '1500.00' },
  items: [
    { id: 'i1', request_item_id: 'r1', sys_number: 'ЗЗ-2026-000001-01', name: 'Швеллер',
      request_id: 'q1', request_number: 'ЗЗ-2026-000001', uom: 'т', plan_qty: '10.000',
      plan_amount: '1000.00', qty: '10.000', amount: '1000.00', qty_available: '10.000' },
    { id: 'i2', request_item_id: 'r2', sys_number: 'ЗЗ-2026-000001-02', name: 'Болт',
      request_id: 'q1', request_number: 'ЗЗ-2026-000001', uom: 'шт', plan_qty: '5.000',
      plan_amount: '500.00', qty: '5.000', amount: '500.00', qty_available: '5.000' },
  ],
  current_holders: null, allowed_actions: ['save', 'submit', 'delete', 'print'],
  ...over,
});

describe('agreementForm', () => {
  it('полная форма из карточки — без ошибок, количества без хвостовых нулей', () => {
    const form = formOf(card());
    expect(form.items[0].qty).toBe('10');
    expect(submitErrors(form, card())).toEqual({});
  });

  it('Σ позиций ≠ сумме договора — BR-033', () => {
    const form = { ...formOf(card()), amount: '1 600,00' };
    expect(submitErrors(form, card()).items_total).toBe(
      'Сумма позиций 1 500,00 не равна сумме договора 1 600,00');
  });

  it('количество больше остатка — BR-042', () => {
    const form = formOf(card());
    form.items[0].qty = '10,5';
    expect(submitErrors(form, card())['item:i1']).toBe('Не больше остатка 10');
  });

  it('обязательные поля договора', () => {
    const form = { ...formOf(card()), counterparty: null, ext_number: '', agreement_type: '' as const };
    const errors = submitErrors(form, card());
    expect(errors.counterparty).toBe('Выберите контрагента');
    expect(errors.ext_number).toBe('Укажите номер договора');
    expect(errors.agreement_type).toBe('Выберите тип договора');
  });

  it('превышение над планом считается по оставленным позициям; у ДС — весь прирост', () => {
    const form = { ...formOf(card()), amount: '1 800,00' };
    expect(overPlan(form, card())).toBe('300.00');
    expect(overPlan({ ...form, items: [form.items[0]] }, card())).toBe('800.00');
    expect(overPlan({ ...form, is_open: true }, card())).toBe('0.00');
    const supplement = card({ parent: { id: 'p', number: 'ДГ-2026-000000' }, items: [] });
    expect(overPlan({ ...formOf(supplement), amount: '250,00' }, supplement)).toBe('250.00');
  });

  it('открытый договор отправляет пустые суммы; ставка — только ручная', () => {
    const form = { ...formOf(card()), is_open: true };
    const patch = patchOf(form, card());
    expect(patch.amount).toBeNull();
    expect(patch.items?.every((item) => item.amount === null)).toBe(true);
    expect('vat_rate' in patch).toBe(false);
    expect(patchOf({ ...formOf(card()), vat_rate: '12', vat_manual: true }, card()).vat_rate)
      .toBe('12');
    // Ставка была ручной, а человек нажал «вернуть справочную» — уходит null.
    const manual = card({ vat_source: 'manual', vat_rate: '10.00' });
    expect(patchOf({ ...formOf(manual), vat_manual: false }, manual).vat_rate).toBeNull();
  });
});

describe('мастер плана: пропорциональная сумма', () => {
  it('часть количества — часть остатка суммы, до копейки', () => {
    expect(proportionalAmount('1000.00', '2,5', '10.000')).toBe('250.00');
    expect(proportionalAmount('100.00', '1', '3.000')).toBe('33.33');
    expect(proportionalAmount('200.00', '2', '3.000')).toBe('133.33');
    expect(proportionalAmount('0.05', '1', '2.000')).toBe('0.03');   // 0,025 → 0,03
    expect(proportionalAmount('1000.00', '10', '10.000')).toBe('1000.00');
  });
});
