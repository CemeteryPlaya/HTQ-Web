import * as React from 'react';

import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import {
  KZ_PHONE_NSN_LENGTH,
  KZ_PHONE_PLACEHOLDER,
  formatNsn,
} from '@/components/ui/phone-input';

/**
 * «Умная» маска телефона с автоопределением страны.
 *
 * - Ввод похож на казахстанский номер (`+7 700…`, `8 700…`, `+7…`) →
 *   форматируется как `+7 (700) 483-55-81`. `+7` показывается подписью
 *   слева от поля, в самом `<input>` живут только 10 цифр национальной
 *   части. Детекция по кодам казахстанских операторов (700-708, 747,
 *   771, 775-778, городские 727, 7172 и др.).
 * - Любой другой ввод (`+49 30…`, `+1 212…`, не присвоенный в KZ код) →
 *   свободный международный формат: разрешены `+`, цифры, пробелы и
 *   разделители `- ( )`, максимум 20 символов.
 *
 * Наружу (`onChange`) уходит:
 *   - KZ    → отформатированная строка `+7 (700) 483-55-81` или `''`;
 *   - INTL  → строка ровно как набрана (пользователь сам выбирает вид).
 */

/** Максимум символов в свободном международном номере. */
export const INTL_PHONE_MAX_LENGTH = 20;

/** Символы, разрешённые в свободном международном номере. */
const INTL_ALLOWED = /[^\d+\s\-()]/g;

export type PhoneRegion = 'kz' | 'intl' | 'empty';

/** Первые 3 цифры национального номера — коды мобильных сетей KZ. */
const KZ_MOBILE_PREFIXES = new Set([
  '700', '701', '702', '705', '708',
  '747', '771', '775', '776', '777', '778',
]);

/** Городские коды KZ: Алматы 727, Астана 7172 и прочие регионы. */
const KZ_CITY_PREFIXES = new Set([
  '727', '7172', '717', '721', '722', '723', '724', '725', '726',
  '728', '729', '711', '712', '713', '714', '715', '716', '718', '719',
]);

/**
 * Национальная часть (10 цифр) из значения, которое хранится в пропсах.
 *
 * KZ-значения приходят в виде `+7 (700) 483-55-81`, `+77004835581` и т.п. —
 * тут ведущая `7` после `+` это код страны, её срезаем. Всё остальное
 * (свободный INTL, текст без `+`) считаем уже национальной частью.
 */
function nsnFromValue(raw: string | null | undefined): string {
  const text = String(raw ?? '');
  if (/^\+\s*7\s*/.test(text)) {
    return text.replace(/^\+\s*7\s*/, '').replace(/\D/g, '').slice(0, KZ_PHONE_NSN_LENGTH);
  }
  return text.replace(/\D/g, '').slice(0, KZ_PHONE_NSN_LENGTH);
}

/**
 * Похож ли набранный номер на казахстанский.
 *
 * Пока национальная часть короче 3 цифр — считаем номер KZ априори
 * (пользователь почти наверняка вводит `+7 700…`). После 3-й цифры смотрим
 * на код оператора: как только он выходит за пределы диапазонов KZ —
 * переключаемся на свободный международный ввод (например `+7 999…`).
 */
export function isKzPhoneLike(raw: string | null | undefined): boolean {
  const text = String(raw ?? '');
  const allDigits = text.replace(/\D/g, '');

  let nsn = nsnFromValue(raw);
  if (allDigits.length > KZ_PHONE_NSN_LENGTH && allDigits.startsWith('8')) {
    // Межгород: `87004835581` — полный номер, ведущая 8 не национальная.
    nsn = allDigits.slice(1, KZ_PHONE_NSN_LENGTH + 1);
  }

  if (nsn.length < 3) {
    return allDigits.startsWith('7') || allDigits.startsWith('8');
  }

  const prefix = nsn.slice(0, 3);
  return KZ_MOBILE_PREFIXES.has(prefix) || KZ_CITY_PREFIXES.has(prefix);
}

export interface InternationalPhoneInputProps
  extends Omit<
    React.ComponentProps<'input'>,
    'value' | 'onChange' | 'type' | 'maxLength'
  > {
  value: string;
  /** Получает отформатированный номер (KZ) или строку как набрана (INTL). */
  onChange: (value: string) => void;
}

export const InternationalPhoneInput: React.FC<InternationalPhoneInputProps> = ({
  value,
  onChange,
  className,
  placeholder,
  disabled,
  readOnly,
  ...rest
}) => {
  const kz = isKzPhoneLike(value) || !String(value ?? '').trim();
  const isEmpty = !String(value ?? '').trim();

  const region: PhoneRegion = isEmpty ? 'empty' : isKzPhoneLike(value) ? 'kz' : 'intl';

  /** Цифры, которые пользователь видит/правит в KZ-режиме (без `+7`). */
  const kzDigits = nsnFromValue(value);

  const emitKz = React.useCallback(
    (digits: string) => {
      onChange(digits ? `+7 ${formatNsn(digits.slice(0, KZ_PHONE_NSN_LENGTH))}` : '');
    },
    [onChange],
  );

  const handleChange = React.useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      const text = event.target.value;

      if (!text.trim() || text === '(') {
        emitKz('');
        return;
      }

      if (isKzPhoneLike(text)) {
        // В KZ-поле лежит национальная часть без `+7` — берём цифры как есть.
        emitKz(text.replace(/\D/g, ''));
        return;
      }

      // INTL-режим: чистим от недопустимых символов без переформатирования.
      onChange(text.replace(INTL_ALLOWED, '').slice(0, INTL_PHONE_MAX_LENGTH));
    },
    [emitKz, onChange],
  );

  const handlePaste = React.useCallback(
    (event: React.ClipboardEvent<HTMLInputElement>) => {
      if (readOnly || disabled) return;
      const pasted = event.clipboardData.getData('text');
      if (!pasted.trim()) return;
      event.preventDefault();

      if (isKzPhoneLike(pasted)) {
        // Вставленный полный номер (`+7 700 483 55 81`, `87004835581`)
        // извлекаем национальную часть и форматируем.
        const allDigits = pasted.replace(/\D/g, '');
        let nsn = nsnFromValue(pasted);
        if (allDigits.length > KZ_PHONE_NSN_LENGTH && allDigits.startsWith('8')) {
          nsn = allDigits.slice(1, KZ_PHONE_NSN_LENGTH + 1);
        }
        emitKz(nsn);
        return;
      }
      onChange(
        pasted.replace(INTL_ALLOWED, '').slice(0, INTL_PHONE_MAX_LENGTH),
      );
    },
    [emitKz, onChange, readOnly, disabled],
  );

  return (
    <div className="relative w-full">
      {kz && (
        <span
          aria-hidden="true"
          className={cn(
            'pointer-events-none absolute inset-y-0 left-3 flex items-center text-base md:text-sm',
            kzDigits ? 'text-foreground' : 'text-muted-foreground',
            disabled && 'opacity-50',
          )}
        >
          +7
        </span>
      )}
      <Input
        {...rest}
        type="tel"
        inputMode="tel"
        autoComplete="tel"
        // KZ-режим: в поле только национальная часть `(700) 483-55-81`,
        // `+7` показан подписью слева. INTL — свободный ввод как набрано.
        value={kz ? formatNsn(kzDigits) : value}
        onChange={handleChange}
        onPaste={handlePaste}
        placeholder={
          placeholder ??
          (region === 'kz' || region === 'empty'
            ? KZ_PHONE_PLACEHOLDER
            : '+1 212 000 00 00')
        }
        maxLength={kz ? 15 : INTL_PHONE_MAX_LENGTH}
        disabled={disabled}
        readOnly={readOnly}
        className={cn('pr-12', kz && 'pl-9', className)}
      />
      {region !== 'empty' && (
        <Badge
          variant="outline"
          className={cn(
            'pointer-events-none absolute inset-y-0 right-2 my-auto flex h-5 items-center rounded px-1.5 font-mono text-[10px] font-semibold uppercase tracking-wide',
            region === 'kz'
              ? 'bg-primary/10 text-primary border-primary/30'
              : 'bg-muted text-muted-foreground border-border',
          )}
        >
          {region === 'kz' ? 'KZ' : 'INTL'}
        </Badge>
      )}
    </div>
  );
};

export default InternationalPhoneInput;
