import * as React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import {
  InternationalPhoneInput,
  isKzPhoneLike,
} from './international-phone-input';

describe('isKzPhoneLike', () => {
  it.each([
    ['+7 (700) 483-55-81', true], // мобильный KZ
    ['+77004835581', true],
    ['87004835581', true], // межгород
    ['8 (700) 483-55-81', true],
    ['+7 (727) 123-45-67', true], // городской Алматы
    ['+7 (7172) 12-34-56', true], // городской Астана
    ['+7 (701) 111-22-33', true],
    ['+49 30 123456', false], // Германия
    ['+1 212 555 0100', false], // США
    ['+7 999 123 45 67', false], // не присвоенный в KZ код
    ['+7', true], // огрызок — априори KZ
    ['', false],
    [null, false],
  ])('%s → %s', (raw, expected) => {
    expect(isKzPhoneLike(raw as string | null)).toBe(expected);
  });
});

function Harness({ initial = '' }: { initial?: string }) {
  const [value, setValue] = React.useState(initial);
  return (
    <>
      <InternationalPhoneInput aria-label="phone" value={value} onChange={setValue} />
      <output data-testid="emitted">{value}</output>
    </>
  );
}

const field = () => screen.getByLabelText('phone') as HTMLInputElement;
const emitted = () => screen.getByTestId('emitted').textContent;

describe('InternationalPhoneInput', () => {
  it('форматирует казахстанский номер и отдаёт наружу полный', () => {
    render(<Harness />);
    fireEvent.change(field(), { target: { value: '(700) 483-55-81' } });
    expect(field().value).toBe('(700) 483-55-81');
    expect(emitted()).toBe('+7 (700) 483-55-81');
  });

  it('не даёт написать больше 10 цифр в KZ-режиме', () => {
    render(<Harness />);
    expect(field().maxLength).toBe(15); // длина "(700) 483-55-81"

    fireEvent.change(field(), { target: { value: '70048355819999' } });
    expect(field().value).toBe('(700) 483-55-81');
    expect(emitted()).toBe('+7 (700) 483-55-81');
  });

  it('игнорирует буквы и лишние символы в KZ-режиме', () => {
    render(<Harness />);
    fireEvent.change(field(), { target: { value: 'abc700x483--55..81' } });
    expect(emitted()).toBe('+7 (700) 483-55-81');
  });

  it('поле можно полностью очистить (наружу уходит "")', () => {
    render(<Harness initial="+7 (700) 483-55-81" />);
    fireEvent.change(field(), { target: { value: '' } });
    expect(field().value).toBe('');
    expect(emitted()).toBe('');
  });

  it('вставка казахстанского номера нормализуется', () => {
    render(<Harness />);
    fireEvent.paste(field(), {
      clipboardData: { getData: () => '8 (701) 111-22-33' },
    });
    expect(emitted()).toBe('+7 (701) 111-22-33');
  });

  it('переключается на свободный международный ввод, если код не KZ', () => {
    render(<Harness initial="+7 (999) 123-45-67" />);
    // «Неприсвоенный» код 999 переводит поле в INTL-режим: значение
    // отображается как набрано и в INTL-режиме не переформатируется.
    expect(field().value).toBe('+7 (999) 123-45-67');
    expect(screen.getByText('INTL')).toBeTruthy();
  });

  it('в INTL-режиме оставляет номер как набран', () => {
    render(<Harness initial="+49 30 123456" />);
    expect(field().value).toBe('+49 30 123456');

    fireEvent.change(field(), { target: { value: '+49 30 123456789' } });
    expect(emitted()).toBe('+49 30 123456789');
  });

  it('в INTL-режиме отсекает недопустимые символы и лимит 20', () => {
    render(<Harness initial="+1" />);
    expect(field().maxLength).toBe(20);

    fireEvent.change(field(), {
      target: { value: '+1 (212) 555-0100 abc!?12345678901234567890' },
    });
    const out = emitted() ?? '';
    // буквы, ! и ? отброшены; остались только разрешённые символы
    expect(out).not.toMatch(/[^\d+\s\-()]/);
    // лимит 20 символов соблюдён
    expect(out.length).toBeLessThanOrEqual(20);
    expect(out).toContain('+1 (212) 555-0100');
  });



  it('показывает legacy-казахстанский номер уже по маске с бейджем KZ', () => {
    render(<Harness initial="+7 700 000 00 00" />);
    expect(field().value).toBe('(700) 000-00-00');
    expect(screen.getByText('KZ')).toBeTruthy();
  });

  it('backspace в KZ-режиме не залипает на разделителях', () => {
    render(<Harness initial="+7 (700) 483-55-81" />);
    for (const expected of [
      '(700) 483-55-8',
      '(700) 483-55',
      '(700) 483-5',
      '(700) 483',
      '(700) 48',
      '(700) 4',
      '(700',
      '(70',
      '(7',
      '',
    ]) {
      fireEvent.change(field(), { target: { value: field().value.slice(0, -1) } });
      expect(field().value).toBe(expected);
    }
  });
});
