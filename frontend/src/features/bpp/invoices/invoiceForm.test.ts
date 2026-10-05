/**
 * Правила формы F-05 (ТЗ §10.2–10.3): обязательные поля, Σ строк = сумме
 * счёта (BR-044), количество ≤ остатка (BR-042), порог 1000 МРП у счёта без
 * договора (BR-040), реквизиты договора не уходят в PATCH счёта по договору.
 */
import { describe, expect, it } from 'vitest';

import type { InvoiceCard } from './api';
import { formOf, overThreshold, patchOf, submitErrors, toKzt } from './invoiceForm';

const card = (over: Partial<InvoiceCard> = {}): InvoiceCard => ({
  id: 'inv1', number: 'СЧ-2026-000001', status: 'draft', version: 3, author_id: 904,
  author_name: 'Иванов А.', created_at: '2026-09-28T05:00:00Z', basis: 'no_contract',
  initiator_role: 'sn', agreement: null,
  project: { id: 'p1', code: 'П-015', name: 'Объект' },
  article: { id: 'art', code: 'T-METAL', name: 'Металлопрокат' },
  counterparty: {
    id: 'c1', name: 'ТОО «Альфа»', short_name: '', reg_number: '100000000001',
    country_code: 'KZ', is_vat_payer: true, status: 'active', is_verified: true,
  },
  counterparty_confirmed: false, ext_number: '77', ext_date: '2026-09-27',
  amount: '1500.00', currency_code: 'KZT', rate: null, rate_source: 'kzt', amount_kzt: '1500.00',
  threshold: '3932000.00', over_threshold: false, with_vat: true, vat_rate: '16.00',
  vat_source: 'refdata', vat_amount: '206.90', vat_warning: null, purchase_type: 'goods',
  is_advance: false, due_date: '2026-10-10', planned_pay_date: null, fd_decided_at: null,
  status_comment: '', rework_comment: '', author_comment: '', docs_required: {},
  docs_requested_at: null, docs_comment: '', days_waiting_docs: null, recon_status: 'no_data',
  paid_bank_amount: '0.00', paid_amount: '0.00', unpaid_amount: '1500.00', payments: [],
  possible_split: false,
  lines: [
    { id: 'l1', request_item_id: 'r1', sys_number: 'ЗЗ-2026-000001-01', name: 'Швеллер',
      request_id: 'q1', request_number: 'ЗЗ-2026-000001', qty: '10.000', amount: '1000.00',
      plan_amount: '1000.00', qty_available: '10.000', amount_available: '1000.00' },
    { id: 'l2', request_item_id: 'r2', sys_number: 'ЗЗ-2026-000001-02', name: 'Болт',
      request_id: 'q1', request_number: 'ЗЗ-2026-000001', qty: '5.000', amount: '500.00',
      plan_amount: '500.00', qty_available: '5.000', amount_available: '500.00' },
  ],
  current_holders: null, allowed_actions: ['save', 'submit', 'delete', 'cancel'],
  ...over,
});

const TODAY = '2026-09-28';

describe('invoiceForm', () => {
  it('заполненный счёт без ошибок', () => {
    expect(submitErrors(formOf(card()), card(), TODAY)).toEqual({});
  });

  it('Σ строк ≠ сумме счёта, количество сверх остатка, дата счёта в будущем', () => {
    const form = formOf(card());
    form.amount = '1 600,00';
    form.ext_date = '2026-09-29';
    form.purchase_type = '';
    form.lines[1].qty = '6';
    const errors = submitErrors(form, card(), TODAY);
    expect(errors.lines_total).toBe('Сумма строк 1 500,00 не равна сумме счёта 1 600,00');
    expect(errors['line:l2']).toBe('Не больше остатка 5');
    expect(errors.ext_date).toBe('Дата счёта — не позже сегодняшней');
    expect(errors.purchase_type).toBe('Выберите тип приобретения');
  });

  it('счёт по договору — реквизиты договора в PATCH не уходят', () => {
    const byContract = card({ basis: 'contract' });
    const patch = patchOf(formOf(byContract), byContract);
    expect(patch).not.toHaveProperty('counterparty_id');
    expect(patch).not.toHaveProperty('currency_code');
    expect(patch).not.toHaveProperty('with_vat');
    expect(patch.lines).toEqual([
      { id: 'l1', qty: '10.000', amount: '1000.00' },
      { id: 'l2', qty: '5.000', amount: '500.00' },
    ]);
  });

  it('ручной курс уходит, сброс ручного курса — null', () => {
    const usd = card({ currency_code: 'USD', rate: '495.100000', rate_source: 'manual' });
    const form = formOf(usd);
    expect(patchOf(form, usd).rate).toBe('495.100000');
    form.rate_manual = false;
    expect(patchOf(form, usd).rate).toBeNull();
  });

  it('порог 1000 МРП: тенге — по сумме, валюта — по курсу, договор — не применим', () => {
    const form = formOf(card());
    form.amount = '3 932 000,01';
    expect(overThreshold(form, card(), '3932000.00')).toBe(true);
    form.amount = '3 932 000,00';
    expect(overThreshold(form, card(), '3932000.00')).toBe(false);

    const usd = card({ currency_code: 'USD', rate: '500.000000', rate_source: 'nbrk' });
    const usdForm = formOf(usd);
    usdForm.amount = '8 000,00';
    expect(overThreshold(usdForm, usd, '3932000.00')).toBe(true);

    expect(overThreshold(formOf(card({ basis: 'contract' })), card({ basis: 'contract' }),
      '3932000.00')).toBeNull();
  });

  it('сумма в тенге по курсу — до тиына, половина вверх', () => {
    expect(toKzt('100.00', '495.123456')).toBe('49512.35');
    expect(toKzt('0.01', '0.5')).toBe('0.01');
    expect(toKzt('10', 'abc')).toBeNull();
  });
});
