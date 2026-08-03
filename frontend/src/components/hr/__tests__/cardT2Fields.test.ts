import { describe, expect, it } from 'vitest';

import {
  buildCardT2Payload,
  emptyT2Form,
  isT2SectionDirty,
  t2FormFromServer,
  validateT2Money,
} from '@/components/hr/cardT2Fields';

describe('emptyT2Form', () => {
  it('заводит все поля всех трёх секций пустыми строками', () => {
    const form = emptyT2Form();
    expect(Object.keys(form).sort()).toEqual(['certs', 'financial', 'personal']);
    expect(form.financial).toEqual({ salary: '', bonus: '', bank_account: '' });
    expect(form.certs.sro_permit_expiry).toBe('');
  });
});

describe('t2FormFromServer', () => {
  it('подставляет пришедшие значения, null превращает в пустую строку', () => {
    const form = t2FormFromServer({
      financial: { salary: '450000.00', bonus: null, bank_account: 'KZ42' },
    });
    expect(form.financial.salary).toBe('450000.00');
    expect(form.financial.bonus).toBe('');
    expect(form.financial.bank_account).toBe('KZ42');
  });

  it('секция, которой нет в ответе (нет права view), остаётся пустой', () => {
    const form = t2FormFromServer({ certs: { sro_permit_number: 'СРО-7', sro_permit_expiry: null, safety_cert_number: null, safety_cert_expiry: null } });
    expect(form.financial.salary).toBe('');
    expect(form.certs.sro_permit_number).toBe('СРО-7');
  });

  it('undefined даёт пустую форму', () => {
    expect(t2FormFromServer(undefined)).toEqual(emptyT2Form());
  });
});

describe('isT2SectionDirty', () => {
  it('false, когда ничего не трогали', () => {
    const initial = t2FormFromServer({ financial: { salary: '100', bonus: null, bank_account: null } });
    expect(isT2SectionDirty(structuredClone(initial), initial, 'financial')).toBe(false);
  });

  it('true при изменении любого поля секции', () => {
    const initial = emptyT2Form();
    const form = structuredClone(initial);
    form.personal.citizenship = 'KZ';
    expect(isT2SectionDirty(form, initial, 'personal')).toBe(true);
    expect(isT2SectionDirty(form, initial, 'financial')).toBe(false);
  });
});

describe('buildCardT2Payload', () => {
  it('отдаёт только изменённые секции из разрешённых', () => {
    const initial = emptyT2Form();
    const form = structuredClone(initial);
    form.financial.salary = '450000';
    form.certs.sro_permit_number = 'СРО-7';

    const payload = buildCardT2Payload(form, initial, ['financial', 'personal', 'certs']);

    expect(Object.keys(payload!).sort()).toEqual(['certs', 'financial']);
  });

  it('не отдаёт секцию, которой нет в списке разрешённых, даже если она изменена', () => {
    const initial = emptyT2Form();
    const form = structuredClone(initial);
    form.financial.salary = '450000';

    expect(buildCardT2Payload(form, initial, ['certs'])).toBeUndefined();
  });

  it('пустое поле уходит null, а не пустой строкой', () => {
    const initial = emptyT2Form();
    const form = structuredClone(initial);
    form.financial.salary = '450000';

    const payload = buildCardT2Payload(form, initial, ['financial'])!;
    expect(payload.financial).toEqual({ salary: '450000', bonus: null, bank_account: null });
  });

  it('нормализует запятую в сумме к точке', () => {
    const initial = emptyT2Form();
    const form = structuredClone(initial);
    form.financial.bonus = '1000,50';

    expect(buildCardT2Payload(form, initial, ['financial'])!.financial!.bonus).toBe('1000.50');
  });

  it('undefined, когда не изменено ничего — запрос не должен нести card_t2', () => {
    const initial = t2FormFromServer({ financial: { salary: '1', bonus: null, bank_account: null } });
    expect(buildCardT2Payload(structuredClone(initial), initial, ['financial'])).toBeUndefined();
  });
});

describe('validateT2Money', () => {
  it('ловит нечисловую сумму и возвращает ключ вида section.field', () => {
    const form = emptyT2Form();
    form.financial.salary = 'много';
    expect(Object.keys(validateT2Money(form, ['financial']))).toEqual(['financial.salary']);
  });

  it('пропускает пустое и валидное', () => {
    const form = emptyT2Form();
    form.financial.salary = '450000,50';
    expect(validateT2Money(form, ['financial'])).toEqual({});
  });

  it('не смотрит на секции вне списка разрешённых', () => {
    const form = emptyT2Form();
    form.financial.salary = 'много';
    expect(validateT2Money(form, ['certs'])).toEqual({});
  });
});
