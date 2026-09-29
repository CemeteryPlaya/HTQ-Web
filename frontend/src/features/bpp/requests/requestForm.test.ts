/**
 * Правила формы F-02 (ТЗ §7.3–7.6): сумма позиции CALC-004 без `float`,
 * «Остаток после заявки», проверки перед отправкой, вставка из Excel.
 */
import { describe, expect, it } from 'vitest';

import {
  afterRequest, emptyItem, lineAmount, parsePastedItems, parseQtyInput, requestInput,
  submitErrors, totalAmount, type EditItem, type RequestFormState,
} from './requestForm';

const TODAY = '2026-09-28';

const item = (over: Partial<EditItem> = {}): EditItem => ({
  ...emptyItem('2026-10-15', 'uom-pcs'), name: 'Швеллер 12П', qty: '10', price: '240 000,00',
  ...over,
});

const form = (over: Partial<RequestFormState> = {}): RequestFormState => ({
  initiator_role: 'sn', project_id: 'p', article_id: 'a', purchase_type: 'goods',
  need_date: '2026-10-15', justification: 'Нужно для монтажа каркаса', items: [item()],
  ...over,
});

describe('CALC-004 и итог', () => {
  it('сумма позиции — ROUND(кол-во × цена, 2), половина — вверх', () => {
    expect(lineAmount('10', '240 000,00')).toBe('2400000.00');
    expect(lineAmount('0,333', '10,00')).toBe('3.33');
    expect(lineAmount('0,335', '1,00')).toBe('0.34');   // 0.335 → 0.34
    expect(lineAmount('1,5', '0,10')).toBe('0.15');
    expect(lineAmount('abc', '1')).toBeNull();
  });

  it('количество — до трёх знаков после запятой', () => {
    expect(parseQtyInput('1 250,5')).toBe('1250.500');
    expect(parseQtyInput('0,0001')).toBeNull();
  });

  it('сумма заявки — Σ позиций, нечисловые не считаются', () => {
    expect(totalAmount([item(), item({ qty: '1', price: '0,10' }), item({ qty: '' })]))
      .toBe('2400000.10');
  });

  it('«Остаток после заявки» вычитает сумму, пока заявка не в резерве', () => {
    expect(afterRequest('2400000.00', '3650000.00', false)).toBe('-1250000.00');
    expect(afterRequest('1600000.00', '2400000.00', true)).toBe('1600000.00');
    expect(afterRequest(null, '1.00', false)).toBeNull();
  });
});

describe('submitErrors', () => {
  it('полная заявка — без ошибок', () => {
    expect(submitErrors(form(), TODAY)).toEqual({});
  });

  it('обязательные поля шапки, обоснование и дата', () => {
    const errors = submitErrors(form({
      article_id: '', purchase_type: '', need_date: '2026-09-01', justification: 'коротко',
    }), TODAY);
    expect(errors.article_id).toBe('Выберите статью бюджета');
    expect(errors.purchase_type).toBe('Выберите вид закупки');
    expect(errors.need_date).toMatch(/не раньше сегодняшней/);
    expect(errors.justification).toMatch(/не короче 10/);
  });

  it('позиции: нужна хотя бы одна, у каждой — имя, ед., кол-во и цена > 0', () => {
    expect(submitErrors(form({ items: [] }), TODAY).items).toBe('Добавьте хотя бы одну позицию');
    const bad = item({ key: 'x', qty: '0' });
    expect(submitErrors(form({ items: [bad] }), TODAY)['item:x']).toBe('Количество — больше нуля');
    const noUom = item({ key: 'y', uom_id: '' });
    expect(submitErrors(form({ items: [noUom] }), TODAY)['item:y']).toBe('Выберите единицу измерения');
  });
});

describe('вставка из Excel', () => {
  const uoms = [
    { id: 'uom-pcs', code: 'pcs', short_name: 'шт' },
    { id: 'uom-t', code: 't', short_name: 'т' },
  ];

  it('колонки Наименование / Ед. / Кол-во / Цена, заголовок пропускается', () => {
    const rows = parsePastedItems(
      'Наименование\tЕд.\tКол-во\tЦена\nШвеллер 12П\tТ\t10\t240 000,00\r\nБолт М12\tшт\t500\t150\n\n',
      uoms, '2026-10-15',
    );
    expect(rows.map((row) => [row.name, row.uom_id, row.qty, row.price, row.need_date])).toEqual([
      ['Швеллер 12П', 'uom-t', '10', '240 000,00', '2026-10-15'],
      ['Болт М12', 'uom-pcs', '500', '150', '2026-10-15'],
    ]);
  });

  it('незнакомая единица остаётся пустой — форма её подсветит', () => {
    expect(parsePastedItems('Кабель\tбухта\t3\t1000', uoms, '')[0].uom_id).toBe('');
  });
});

describe('requestInput', () => {
  it('числа уходят строками сервера', () => {
    const body = requestInput(form());
    expect(body.items[0]).toMatchObject({ qty: '10.000', price: '240000.00', uom_id: 'uom-pcs' });
    expect(body.justification).toBe('Нужно для монтажа каркаса');
  });
});
