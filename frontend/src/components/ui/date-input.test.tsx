/**
 * Маска даты: проверяется то, ради чего она и заведена.
 *
 * Нативный `<input type="date">`, стоявший в форме раньше, на несуществующей
 * дате просто ничего не отдаёт — поле выглядит пустым, и человек не понимает,
 * что не так. Поэтому здесь отдельно закреплено: «31.02.2026» распознаётся
 * как ОШИБКА, а не как пустота.
 */
import { render, screen, fireEvent } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { DateInput, fromIsoDate, maskDate, toIsoDate } from '@/components/ui/date-input';

describe('разбор и показ', () => {
  it('ставит точки сама, пока набирают цифры', () => {
    expect(maskDate('0')).toBe('0');
    expect(maskDate('01')).toBe('01');
    expect(maskDate('0102')).toBe('01.02');
    expect(maskDate('01022026')).toBe('01.02.2026');
  });

  it('терпит вставку в любом виде', () => {
    expect(maskDate('01.02.2026')).toBe('01.02.2026');
    expect(maskDate('01/02/2026')).toBe('01.02.2026');
    expect(maskDate('01022026лишнее')).toBe('01.02.2026');
  });

  it('переводит в ISO только дописанную и существующую дату', () => {
    expect(toIsoDate('01.02.2026')).toBe('2026-02-01');
    expect(toIsoDate('01.02.20')).toBeNull();      // недописано
    expect(toIsoDate('31.02.2026')).toBeNull();    // такого дня нет
    expect(toIsoDate('01.13.2026')).toBeNull();    // такого месяца нет
    expect(toIsoDate('01.02.0202')).toBeNull();    // опечатка в годе
  });

  it('високосный год отличает от обычного', () => {
    expect(toIsoDate('29.02.2028')).toBe('2028-02-29');
    expect(toIsoDate('29.02.2026')).toBeNull();
  });

  it('показывает ISO в привычном виде', () => {
    expect(fromIsoDate('2026-02-01')).toBe('01.02.2026');
    expect(fromIsoDate('')).toBe('');
    expect(fromIsoDate(null)).toBe('');
  });
});

describe('поле', () => {
  it('отдаёт ISO наружу, когда дата дособрана', () => {
    const onChange = vi.fn();
    render(<DateInput aria-label="Дата" value="" onChange={onChange} />);
    fireEvent.change(screen.getByLabelText('Дата'), { target: { value: '01022026' } });
    expect(onChange).toHaveBeenCalledWith('2026-02-01');
  });

  it('пока дата не дособрана, значение наружу пустое', () => {
    const onChange = vi.fn();
    render(<DateInput aria-label="Дата" value="" onChange={onChange} />);
    fireEvent.change(screen.getByLabelText('Дата'), { target: { value: '0102' } });
    expect(onChange).toHaveBeenCalledWith('');
  });

  it('о несуществующей дате сообщает форме, а не молчит', () => {
    const onValidityChange = vi.fn();
    render(
      <DateInput aria-label="Дата" value="" onChange={vi.fn()}
        onValidityChange={onValidityChange} />,
    );
    fireEvent.change(screen.getByLabelText('Дата'), { target: { value: '31022026' } });
    expect(onValidityChange).toHaveBeenLastCalledWith(true);
  });

  it('пустое поле ошибкой не считает: обязательность — дело формы', () => {
    const onValidityChange = vi.fn();
    render(
      <DateInput aria-label="Дата" value="2026-02-01" onChange={vi.fn()}
        onValidityChange={onValidityChange} />,
    );
    fireEvent.change(screen.getByLabelText('Дата'), { target: { value: '' } });
    expect(onValidityChange).toHaveBeenLastCalledWith(false);
  });

  it('не съедает набранное, пока дата не дособрана', () => {
    // Форма держит ISO, и на недописанной дате он пустой. Если поле начнёт
    // «синхронизироваться» с этой пустотой, перепечатать готовую дату будет
    // нельзя: первый же символ исчезнет.
    function Form() {
      const [value, setValue] = useState('2026-02-01');
      return <DateInput aria-label="Дата" value={value} onChange={setValue} />;
    }
    render(<Form />);
    const field = screen.getByLabelText('Дата');
    expect(field).toHaveValue('01.02.2026');

    fireEvent.change(field, { target: { value: '0' } });
    expect(field).toHaveValue('0');

    fireEvent.change(field, { target: { value: '05032026' } });
    expect(field).toHaveValue('05.03.2026');
  });

  it('показывает пришедшее снаружи значение', () => {
    render(<DateInput aria-label="Дата" value="2026-12-31" onChange={vi.fn()} />);
    expect(screen.getByLabelText('Дата')).toHaveValue('31.12.2026');
  });
});
