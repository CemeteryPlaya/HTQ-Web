import * as React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { BinIinInput, binIinDigits, isKzBinIin } from './bin-iin-input';

describe('binIinDigits', () => {
    it.each([
        ['123456789012', '123456789012'], // наш собственный формат
        ['1234 5678 9012', '123456789012'], // с разделителями
        ['123-456-789-012', '123456789012'],
        ['abc123456789012xyz', '123456789012'], // всё, кроме цифр, — мусор
        ['123', '123'], // недобранный
        ['', ''],
        [null, ''],
    ])('%s → %s', (raw, expected) => {
        expect(binIinDigits(raw as string | null)).toBe(expected);
    });

    it('обрезает всё, что длиннее 12 цифр', () => {
        expect(binIinDigits('1234567890123456')).toBe('123456789012');
    });
});

describe('isKzBinIin', () => {
    it('полным считается только БИН/ИИН из 12 цифр', () => {
        expect(isKzBinIin('123456789012')).toBe(true);
        expect(isKzBinIin('12345678901')).toBe(false);
        expect(isKzBinIin('')).toBe(false);
    });
});

function Harness({ initial = '' }: { initial?: string }) {
    const [value, setValue] = React.useState(initial);
    return (
        <>
            <BinIinInput aria-label="bin" value={value} onChange={setValue} />
            <output data-testid="emitted">{value}</output>
        </>
    );
}

const field = () => screen.getByLabelText('bin') as HTMLInputElement;
const emitted = () => screen.getByTestId('emitted').textContent;

describe('BinIinInput', () => {
    it('форматирует набранные цифры слитно и отдаёт наружу без разделителей', () => {
        render(<Harness />);
        fireEvent.change(field(), { target: { value: '1234 5678 9012' } });
        expect(field().value).toBe('123456789012');
        expect(emitted()).toBe('123456789012');
    });

    it('не даёт написать больше 12 цифр', () => {
        render(<Harness />);
        expect(field().maxLength).toBe(12);

        // даже в обход maxLength лишние цифры отбрасываются
        fireEvent.change(field(), { target: { value: '1234567890129999' } });
        expect(field().value).toBe('123456789012');
        expect(emitted()).toBe('123456789012');
    });

    it('игнорирует буквы и лишние символы', () => {
        render(<Harness />);
        fireEvent.change(field(), { target: { value: 'ab123-456x789012з' } });
        expect(emitted()).toBe('123456789012');
    });

    it('поле можно полностью очистить', () => {
        render(<Harness initial="123456789012" />);
        fireEvent.change(field(), { target: { value: '' } });
        expect(field().value).toBe('');
        expect(emitted()).toBe('');
    });

    it('показывает legacy-значение уже очищенным от разделителей', () => {
        render(<Harness initial="1234 5678 9012" />);
        expect(field().value).toBe('123456789012');
    });

    it('вставка целого значения нормализуется', () => {
        render(<Harness initial="123456789012" />);
        fireEvent.paste(field(), {
            clipboardData: { getData: () => '9876 5432 1098' },
        });
        expect(emitted()).toBe('987654321098');
    });
});
