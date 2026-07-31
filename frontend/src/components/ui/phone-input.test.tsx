import * as React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import {
    PhoneInput,
    formatKzPhone,
    isKzPhoneComplete,
    isKzPhoneValid,
    kzPhoneDigits,
} from './phone-input';

describe('kzPhoneDigits', () => {
    it.each([
        ['+7 (700) 483-55-81', '7004835581'], // наш собственный формат
        ['+77004835581', '7004835581'],
        ['87004835581', '7004835581'], // межгород
        ['8 (700) 483-55-81', '7004835581'],
        ['+7 700 000 00 00', '7000000000'], // legacy-значение из БД
        ['7004835581', '7004835581'], // уже национальный номер
        ['700', '700'], // недобранный
        ['+7', ''], // огрызок старой маски
        ['', ''],
        [null, ''],
    ])('%s → %s', (raw, expected) => {
        expect(kzPhoneDigits(raw)).toBe(expected);
    });

    it('обрезает всё, что длиннее 10 цифр', () => {
        expect(kzPhoneDigits('+7 (700) 483-55-81 99999')).toBe('7004835581');
    });

    it('не считает кодом страны семёрку внутри 10-значного номера', () => {
        // 727 — Алматы; ведущая 7 здесь часть номера, а не код страны.
        expect(kzPhoneDigits('7273334455')).toBe('7273334455');
    });
});

describe('formatKzPhone / валидность', () => {
    it('приводит любой ввод к единой форме', () => {
        expect(formatKzPhone('87004835581')).toBe('+7 (700) 483-55-81');
        expect(formatKzPhone('')).toBe('');
    });

    it('полным считается только номер из 10 цифр', () => {
        expect(isKzPhoneComplete('+7 (700) 483-55-81')).toBe(true);
        expect(isKzPhoneComplete('+7 (700) 483')).toBe(false);
        expect(isKzPhoneValid('')).toBe(true); // пусто — допустимо
        expect(isKzPhoneValid('+7 (700) 483')).toBe(false);
    });
});

function Harness({ initial = '' }: { initial?: string }) {
    const [value, setValue] = React.useState(initial);
    return (
        <>
            <PhoneInput aria-label="phone" value={value} onChange={setValue} />
            <output data-testid="emitted">{value}</output>
        </>
    );
}

const field = () => screen.getByLabelText('phone') as HTMLInputElement;
const emitted = () => screen.getByTestId('emitted').textContent;

describe('PhoneInput', () => {
    it('форматирует набранные цифры и отдаёт наружу полный номер', () => {
        render(<Harness />);
        fireEvent.change(field(), { target: { value: '7004835581' } });
        expect(field().value).toBe('(700) 483-55-81');
        expect(emitted()).toBe('+7 (700) 483-55-81');
    });

    it('не даёт написать больше маски', () => {
        render(<Harness />);
        expect(field().maxLength).toBe(15); // длина "(700) 483-55-81"

        // даже в обход maxLength лишние цифры отбрасываются
        fireEvent.change(field(), { target: { value: '70048355819999' } });
        expect(field().value).toBe('(700) 483-55-81');
        expect(emitted()).toBe('+7 (700) 483-55-81');
    });

    it('игнорирует буквы и лишние разделители', () => {
        render(<Harness />);
        fireEvent.change(field(), { target: { value: 'abc700x483--55..81' } });
        expect(emitted()).toBe('+7 (700) 483-55-81');
    });

    it('показывает legacy-значение из БД уже по маске', () => {
        render(<Harness initial="+7 700 000 00 00" />);
        expect(field().value).toBe('(700) 000-00-00');
    });

    it('поле можно полностью очистить', () => {
        render(<Harness initial="+7 (700) 483-55-81" />);
        fireEvent.change(field(), { target: { value: '' } });
        expect(field().value).toBe('');
        expect(emitted()).toBe(''); // не "+7"
    });

    it('backspace не залипает на разделителях', () => {
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

    it('вставка целого номера заменяет поле и нормализуется', () => {
        render(<Harness initial="+7 (700) 483-55-81" />);
        fireEvent.paste(field(), {
            clipboardData: { getData: () => '8 (701) 111-22-33' },
        });
        expect(emitted()).toBe('+7 (701) 111-22-33');
    });
});
