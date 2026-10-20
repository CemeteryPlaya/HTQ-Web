/**
 * Форма предложения поставщика (T3.5; план этапа 3, T3.3): ответ сервера →
 * состояние формы → тело `PUT offer`, проверки до отправки (цена > 0 у
 * участвующей позиции, кол-во ≤ запрошенного, аналог и частичное — только
 * если разрешены, срок действия не в прошлом, доставка и СМР — если
 * запрошены) и сумма предложения.
 */
import { describe, expect, it } from 'vitest';

import { formOf, offerErrors, offerInput, offerTotal } from './offerForm';
import { portalOffer, portalTender } from './testData';

const TODAY = '2026-10-07';

describe('formOf / offerInput', () => {
  it('строки по позициям тендера, суммы с запятой, обратно — строки-десятичные', () => {
    const offer = portalOffer();
    offer.lines[0] = { ...offer.lines[0], price: '365000.00', delivery_date: '2099-11-24' };
    const form = formOf(portalTender(), offer);
    expect(form.lines.map((line) => line.item_id)).toEqual(['it-1', 'it-2']);
    expect(form.lines[0]).toMatchObject({ price: '365 000,00', qty: '10,000', participates: true });

    const body = offerInput(form, offer.version, { requisitesEditable: false });
    expect(body.version).toBe(3);
    expect(body.lines[0]).toEqual({
      item_id: 'it-1', participates: true, price: '365000.00', qty: '10.000',
      delivery_date: '2099-11-24', is_analog: false, analog_note: '', comment: '',
    });
    expect(body.lines[1]).toMatchObject({ item_id: 'it-2', price: null });
    expect(body).toMatchObject({ currency_code: 'KZT', with_vat: true, vat_rate: '12.00', valid_until: '2099-12-31' });
    // Реквизиты известного контрагента сервер правит сам — не отправляем.
    expect(body).not.toHaveProperty('requisites');
  });

  it('позиция без строки в предложении — новая, участвует, кол-во = запрошенному', () => {
    const offer = portalOffer({ lines: [] });
    const form = formOf(portalTender(), offer);
    expect(form.lines[1]).toMatchObject({ item_id: 'it-2', participates: true, qty: '2,500', price: '' });
  });

  it('доставка и СМР — только если запрошены; схема оплаты — шаблоном', () => {
    const tender = portalTender({ needs_works: true, works_scope: 'Монтаж' });
    const form = formOf(tender, portalOffer());
    form.delivery = { amount: '', included_in_price: true, note: '' };
    form.works = { amount: '250 000', included_in_price: false, note: 'Монтаж каркаса' };
    form.scheme = { kind: 'advance', advance_pct: '30', postpay_days: '' };
    const body = offerInput(form, 3, { requisitesEditable: true });
    // Сервер принимает доставку и СМР словарём по виду (`extras.<вид>`), не списком.
    expect(body.extras).toEqual({
      delivery: { amount: null, included_in_price: true, note: '' },
      works: { amount: '250000.00', included_in_price: false, note: 'Монтаж каркаса' },
    });
    expect(body.payment_scheme).toEqual({ kind: 'advance', advance_pct: '30' });
    expect(body.requisites).toMatchObject({ name: 'ТОО «Сталь Трейд»', email: 'tender@stal.kz' });

    const noExtras = offerInput(formOf(portalTender({ needs_delivery: false }), portalOffer()), 3, { requisitesEditable: false });
    expect(noExtras.extras).toEqual({});
  });

  it('пустое предложение (приём закрыт, ничего не сохраняли) — форма без падения', () => {
    const empty = portalOffer({
      id: null, version: null, status: null, number: null, currency_code: null, with_vat: null,
      vat_rate: null, valid_until: null, extra_terms: '', requisites: {} as never, lines: [], extras: [],
      payment_scheme: null, editable: false,
    });
    const form = formOf(portalTender(), empty);
    expect(form.currency_code).toBe('KZT');
    expect(form.with_vat).toBe(false);
    expect(form.requisites.name).toBe('');
    expect(form.lines).toHaveLength(2);
  });

  it('без НДС ставка не уходит', () => {
    const form = formOf(portalTender(), portalOffer());
    form.with_vat = false;
    expect(offerInput(form, 3, { requisitesEditable: false }).vat_rate).toBeNull();
  });
});

describe('offerErrors', () => {
  const filled = () => {
    const form = formOf(portalTender(), portalOffer());
    form.lines = form.lines.map((line) => ({ ...line, price: '1000', delivery_date: '2099-11-24' }));
    return form;
  };

  it('заполненное — без ошибок', () => {
    expect(offerErrors(filled(), portalTender(), TODAY)).toEqual({});
  });

  it('участвующей позиции нужна цена; кол-во не больше запрошенного', () => {
    const form = filled();
    form.lines[0] = { ...form.lines[0], price: '' };
    form.lines[1] = { ...form.lines[1], qty: '3' };
    const errors = offerErrors(form, portalTender(), TODAY);
    expect(errors['line:it-1']).toBe('Укажите цену за единицу больше нуля');
    expect(errors['line:it-2']).toBe('Количество — больше нуля и не больше запрошенного (2,5)');
  });

  it('ни одной участвующей позиции — ошибка', () => {
    const form = filled();
    form.lines = form.lines.map((line) => ({ ...line, participates: false }));
    expect(offerErrors(form, portalTender(), TODAY)).toHaveProperty('lines');
  });

  it('частичное предложение запрещено — нужны все позиции и полное кол-во', () => {
    const tender = portalTender({ allow_partial: false });
    const form = filled();
    form.lines[1] = { ...form.lines[1], participates: false };
    expect(offerErrors(form, tender, TODAY)).toHaveProperty('lines');
    const short = filled();
    short.lines[0] = { ...short.lines[0], qty: '5' };
    expect(offerErrors(short, tender, TODAY)['line:it-1']).toMatch(/полное количество/);
  });

  it('аналог при запрете — ошибка; разрешён — нужно описание', () => {
    const form = filled();
    form.lines[0] = { ...form.lines[0], is_analog: true, analog_note: '' };
    expect(offerErrors(form, portalTender({ allow_analogs: false }), TODAY)['line:it-1']).toMatch(/Аналоги не допускаются/);
    expect(offerErrors(form, portalTender(), TODAY)['line:it-1']).toMatch(/Опишите аналог/);
  });

  it('срок действия не в прошлом; доставка не в цене — нужна сумма', () => {
    const form = filled();
    form.valid_until = '2026-10-01';
    form.delivery = { amount: '', included_in_price: false, note: '' };
    const errors = offerErrors(form, portalTender(), TODAY);
    expect(errors.valid_until).toBeDefined();
    expect(errors.delivery).toBeDefined();
  });
});

describe('offerTotal', () => {
  it('Σ цена × кол-во участвующих + доставка и СМР не в цене', () => {
    const form = formOf(portalTender(), portalOffer());
    form.lines[0] = { ...form.lines[0], price: '1 000,50' };
    form.lines[1] = { ...form.lines[1], price: '200', participates: false };
    form.delivery = { amount: '5000', included_in_price: false, note: '' };
    expect(offerTotal(form)).toBe('15005.00');
  });
});
