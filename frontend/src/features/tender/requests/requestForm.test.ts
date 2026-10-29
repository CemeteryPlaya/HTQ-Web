/**
 * Правила формы заявки на тендер (T1.4, план этапов 0–2 §3.1–3.2): состояние
 * формы ↔ тело запроса, проверки перед отправкой (T-04, T-05) и плановые
 * суммы по статьям — та же группировка, по которой сервер режет заявку на
 * части (позиция без своей статьи идёт по статье заявки).
 */
import { describe, expect, it } from 'vitest';

import type { TenderRequestCard } from './api';
import {
  emptyItem, formOf, planByArticle, requestInput, submitErrors, type TenderRequestForm,
} from './requestForm';

const TODAY = '2026-10-07';

const card = (over: Partial<TenderRequestCard> = {}): TenderRequestCard => ({
  id: 'r1', number: 'ЗТ-2026-000001', status: 'draft', status_display: 'Черновик',
  author_id: 904, author_name: 'Иванов А.', created_at: '2026-10-07T09:00:00+05:00',
  updated_at: '2026-10-07T09:00:00+05:00', initiator_role: 'sn',
  project_id: 'p1', project: { id: 'p1', code: 'П-015', name: 'Объект' }, article_id: 'a-metal', purchase_type: 'goods', need_date: '2026-11-01',
  delivery_address: 'Астана, ул. Сарыарка 1', justification: 'Каркас корпуса Б',
  needs_delivery: true, delivery_article_id: 'a-logistics', delivery_plan_amount: '150000.00',
  needs_works: false, works_scope: '', works_article_id: null, works_plan_amount: null,
  allow_analogs: false, allow_partial: true, rework_comment: '', status_comment: '',
  version: 4, allowed_actions: ['save', 'submit'],
  items: [
    {
      id: 'i1', line_no: 1, name: 'Швеллер 12П', specs: 'ГОСТ 8240', uom_id: 'uom-t',
      qty: '10.000', plan_price: '365000.00', need_date: '2026-11-01', article_id: null,
    },
    {
      id: 'i2', line_no: 2, name: 'Электроды', specs: '', uom_id: 'uom-kg',
      qty: '25.500', plan_price: '1200.00', need_date: '2026-11-01', article_id: 'a-weld',
    },
  ],
  parts: [],
  ...over,
});

const valid = (over: Partial<TenderRequestForm> = {}): TenderRequestForm => ({
  ...formOf(card(), ''),
  ...over,
});

describe('formOf / requestInput', () => {
  it('карточка → форма → тело: суммы и количества с запятой, статья позиции сохраняется', () => {
    const form = formOf(card(), '');
    expect(form.items[0]).toMatchObject({ qty: '10,000', plan_price: '365 000,00', article_id: '' });
    expect(form.items[1].article_id).toBe('a-weld');
    expect(form.delivery_plan_amount).toBe('150 000,00');

    const body = requestInput(form);
    expect(body.items[0]).toMatchObject({ qty: '10.000', plan_price: '365000.00', article_id: null });
    expect(body.items[1]).toMatchObject({ qty: '25.500', plan_price: '1200.00', article_id: 'a-weld' });
    expect(body).toMatchObject({
      project_id: 'p1', article_id: 'a-metal', purchase_type: 'goods', initiator_role: 'sn',
      needs_delivery: true, delivery_article_id: 'a-logistics', delivery_plan_amount: '150000.00',
      needs_works: false, works_article_id: null, works_plan_amount: null, works_scope: '',
      allow_analogs: false, allow_partial: true,
    });
  });

  it('строка с сервера уходит со своим id (правка на месте), новая и копия — без id', () => {
    const form = formOf(card(), '');
    const added = emptyItem('2026-11-01', 'uom-t');
    const copy = { ...form.items[0], key: 'copy-1', id: null };
    const body = requestInput({ ...form, items: [...form.items, { ...added, name: 'Уголок', qty: '1', plan_price: '10' }, copy] });
    expect(body.items.map((item) => item.id)).toEqual(['i1', 'i2', null, null]);
  });

  it('пустое количество и цена уходят null, а не нулём', () => {
    const form = formOf(card(), '');
    form.items[0] = { ...form.items[0], qty: '', plan_price: '' };
    const body = requestInput(form);
    expect(body.items[0]).toMatchObject({ qty: null, plan_price: null });
  });

  it('выключенная доставка не уносит статью и сумму доставки', () => {
    const body = requestInput(valid({ needs_delivery: false }));
    expect(body.delivery_article_id).toBeNull();
    expect(body.delivery_plan_amount).toBeNull();
  });

  it('новая заявка — пустая форма с ролью по умолчанию и видом «ТМЦ»', () => {
    const form = formOf(undefined, 'pm');
    expect(form).toMatchObject({
      initiator_role: 'pm', project_id: '', purchase_type: 'goods', items: [],
      needs_delivery: false, needs_works: false, allow_analogs: false, allow_partial: true,
    });
    expect(emptyItem('2026-12-01', 'uom-pcs')).toMatchObject({
      name: '', uom_id: 'uom-pcs', need_date: '2026-12-01', article_id: '',
    });
  });
});

describe('submitErrors', () => {
  it('заполненная заявка — без ошибок', () => {
    expect(submitErrors(valid(), TODAY)).toEqual({});
  });

  it('обоснование короче 10 символов (T-05) и нет позиций', () => {
    const errors = submitErrors(valid({ justification: 'коротко', items: [] }), TODAY);
    expect(Object.keys(errors).sort()).toEqual(['items', 'justification']);
  });

  it('доставка: нужны статья и плановая сумма больше нуля (T-04)', () => {
    const errors = submitErrors(valid({ delivery_article_id: '', delivery_plan_amount: '0' }), TODAY);
    expect(Object.keys(errors).sort()).toEqual(['delivery_article_id', 'delivery_plan_amount']);
  });

  it('СМР: объём работ, статья и плановая сумма', () => {
    const errors = submitErrors(valid({ needs_works: true }), TODAY);
    expect(Object.keys(errors).sort()).toEqual(['works_article_id', 'works_plan_amount', 'works_scope']);
  });

  it('позиция: наименование от 3 символов, количество и цена больше нуля', () => {
    const form = valid();
    form.items[0] = { ...form.items[0], name: 'аб' };
    form.items[1] = { ...form.items[1], plan_price: '0' };
    const errors = submitErrors(form, TODAY);
    expect(errors[`item:${form.items[0].key}`]).toMatch(/Наименование/);
    expect(errors[`item:${form.items[1].key}`]).toMatch(/Цена/);
  });

  it('проект, статья по умолчанию и дата потребности обязательны', () => {
    const errors = submitErrors(valid({ project_id: '', article_id: '', need_date: '' }), TODAY);
    expect(errors).toHaveProperty('project_id');
    expect(errors).toHaveProperty('article_id');
    expect(errors).toHaveProperty('need_date');
  });
});

describe('planByArticle', () => {
  it('позиции — по своей статье или статье заявки, доставка и СМР — по своим', () => {
    const plan = planByArticle(valid({
      needs_works: true, works_article_id: 'a-works', works_plan_amount: '500 000',
    }));
    expect(Object.fromEntries(plan)).toEqual({
      'a-metal': '3650000.00',
      'a-weld': '30600.00',
      'a-logistics': '150000.00',
      'a-works': '500000.00',
    });
  });

  it('позиции без статьи при пустой статье заявки не считаются', () => {
    const plan = planByArticle(valid({ article_id: '', needs_delivery: false }));
    expect(Object.fromEntries(plan)).toEqual({ 'a-weld': '30600.00' });
  });
});
