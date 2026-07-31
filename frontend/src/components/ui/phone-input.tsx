import * as React from 'react';

import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';

/**
 * Маска ввода казахстанского номера: `+7 (700) 483-55-81`.
 *
 * Код страны `+7` — это неизменяемая подпись слева от поля, а не текст,
 * который можно стереть или продублировать. В самом `<input>` живут только
 * 10 цифр национального номера, поэтому:
 *   - лишние символы физически некуда вписать (`maxLength` + переформат);
 *   - поле можно полностью очистить (наружу уходит `''`, а не огрызок `+7`);
 *   - буквы и любые другие разделители отбрасываются на лету.
 *
 * Наружу (`onChange`) всегда уходит либо `''`, либо полностью
 * отформатированная строка `+7 (700) 483-55-81`.
 */

/** Цифр в номере после кода страны: `700 483 55 81`. */
export const KZ_PHONE_NSN_LENGTH = 10;

/** Длина видимой части `(700) 483-55-81` — жёсткий потолок для `<input>`. */
const KZ_PHONE_NSN_CHARS = 15;

/** Подсказка в пустом поле (код страны показан отдельной подписью). */
export const KZ_PHONE_PLACEHOLDER = '(700) 483-55-81';

/**
 * Достаёт 10 цифр национального номера из произвольной строки: значения из
 * БД (`+7 700 000 00 00`), вставки из буфера (`8 (700) 483-55-81`,
 * `+77004835581`), автозаполнения браузера.
 */
export function kzPhoneDigits(raw: string | null | undefined): string {
    const text = String(raw ?? '');
    let digits = text.replace(/\D/g, '');

    if (text.includes('+') && digits.startsWith('7')) {
        // Явный код страны в тексте: `+7 (700) ...`, `+77004835581`.
        digits = digits.slice(1);
    } else if (digits.length > KZ_PHONE_NSN_LENGTH && /^[78]/.test(digits)) {
        // 11 цифр — первая это код страны (7) или межгород (8).
        // Ровно 10 цифр НЕ трогаем: коды операторов KZ сами начинаются с
        // семёрки (700-708, 747, 771, 775-778, городские 727/7172).
        digits = digits.slice(1);
    }

    return digits.slice(0, KZ_PHONE_NSN_LENGTH);
}

/**
 * Разбор того, что лежит в самом `<input>`. Здесь эвристики «ведущая 7 —
 * это код страны» быть не должно: в поле только национальная часть, и
 * 11-я набранная цифра иначе сдвинула бы весь номер. Ведущую 7 срезаем
 * только при явном `+` (автозаполнение целого номера), ведущую 8 — как
 * межгород, ею казахстанский номер не начинается.
 */
function parseTyped(text: string): string {
    const digits = text.replace(/\D/g, '');
    if (text.includes('+') && digits.startsWith('7')) {
        return digits.slice(1, KZ_PHONE_NSN_LENGTH + 1);
    }
    if (digits.length > KZ_PHONE_NSN_LENGTH && digits.startsWith('8')) {
        return digits.slice(1, KZ_PHONE_NSN_LENGTH + 1);
    }
    return digits.slice(0, KZ_PHONE_NSN_LENGTH);
}

/**
 * `7004835581` → `(700) 483-55-81`.
 *
 * Разделитель появляется только вместе со следующей цифрой. Иначе backspace
 * упирается в него: маска дорисовывает разделитель обратно, значение не
 * меняется, и номер невозможно стереть.
 */
function formatNsn(digits: string): string {
    if (!digits) return '';
    let out = `(${digits.slice(0, 3)}`;
    if (digits.length > 3) out += `) ${digits.slice(3, 6)}`;
    if (digits.length > 6) out += `-${digits.slice(6, 8)}`;
    if (digits.length > 8) out += `-${digits.slice(8, 10)}`;
    return out;
}

/** Любой ввод → `+7 (700) 483-55-81`, либо `''`, если цифр нет. */
export function formatKzPhone(raw: string | null | undefined): string {
    const nsn = kzPhoneDigits(raw);
    return nsn ? `+7 ${formatNsn(nsn)}` : '';
}

/** Номер набран полностью (все 10 цифр). */
export function isKzPhoneComplete(raw: string | null | undefined): boolean {
    return kzPhoneDigits(raw).length === KZ_PHONE_NSN_LENGTH;
}

/** Пусто или полный номер — то, что допустимо сохранять. */
export function isKzPhoneValid(raw: string | null | undefined): boolean {
    const length = kzPhoneDigits(raw).length;
    return length === 0 || length === KZ_PHONE_NSN_LENGTH;
}

export interface PhoneInputProps
    extends Omit<React.ComponentProps<'input'>, 'value' | 'onChange' | 'type' | 'maxLength'> {
    value: string;
    /** Получает `+7 (700) 483-55-81` или `''`, если поле очистили. */
    onChange: (value: string) => void;
}

export const PhoneInput: React.FC<PhoneInputProps> = ({
    value,
    onChange,
    className,
    placeholder = KZ_PHONE_PLACEHOLDER,
    disabled,
    readOnly,
    ...rest
}) => {
    const nsn = kzPhoneDigits(value);

    const emit = React.useCallback(
        (digits: string) => {
            onChange(digits ? `+7 ${formatNsn(digits)}` : '');
        },
        [onChange],
    );

    const handleChange = React.useCallback(
        (event: React.ChangeEvent<HTMLInputElement>) => {
            emit(parseTyped(event.target.value));
        },
        [emit],
    );

    // Вставку обрабатываем отдельно: браузер обрезал бы её по maxLength
    // (`+7 (700) 483-55-81` — 18 символов), покалечив номер. Вставленное
    // всегда заменяет поле целиком — так номер из буфера не склеивается с
    // уже набранным.
    const handlePaste = React.useCallback(
        (event: React.ClipboardEvent<HTMLInputElement>) => {
            if (readOnly || disabled) return;
            const pasted = event.clipboardData.getData('text');
            if (!pasted.trim()) return;
            event.preventDefault();
            emit(kzPhoneDigits(pasted));
        },
        [emit, readOnly, disabled],
    );

    return (
        <div className="relative w-full">
            <span
                aria-hidden="true"
                className={cn(
                    'pointer-events-none absolute inset-y-0 left-3 flex items-center text-base md:text-sm',
                    nsn ? 'text-foreground' : 'text-muted-foreground',
                    disabled && 'opacity-50',
                )}
            >
                +7
            </span>
            <Input
                {...rest}
                type="tel"
                inputMode="tel"
                autoComplete="tel"
                value={formatNsn(nsn)}
                onChange={handleChange}
                onPaste={handlePaste}
                placeholder={placeholder}
                maxLength={KZ_PHONE_NSN_CHARS}
                disabled={disabled}
                readOnly={readOnly}
                className={cn('pl-9', className)}
            />
        </div>
    );
};

export default PhoneInput;
