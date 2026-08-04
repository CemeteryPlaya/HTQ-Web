import * as React from 'react';

import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';

/**
 * Маска казахстанского БИН/ИИН: `123456789012` (12 цифр, слитно).
 *
 * Поведение:
 *   - пропускает только цифры, всё остальное отбрасывается на лету;
 *   - максимум 12 цифр (`maxLength` + переформат) — лишнее физически
 *     не вписать;
 *   - «мягкая»: если набрано не 12 цифр, значение всё равно отдаётся
 *     наружу — иностранные номера форм другой давности не 12-значные,
 *     и блокировать их сохранение маска не должна.
 *
 * Наружу (`onChange`) всегда уходит строка только из цифр (или `''`),
 * без разделителей — бэкенд ожидает именно 12-значное число.
 */

/** Точная длина казахстанского БИН/ИИН. */
export const KZ_BIN_IIN_LENGTH = 12;

/** Цифры из произвольной строки: вставляли «1234 5678 9012» или «123-456…». */
export function binIinDigits(raw: string | null | undefined): string {
  return String(raw ?? '').replace(/\D/g, '').slice(0, KZ_BIN_IIN_LENGTH);
}

/** Казахстанский БИН/ИИН — ровно 12 цифр. */
export function isKzBinIin(raw: string | null | undefined): boolean {
  return binIinDigits(raw).length === KZ_BIN_IIN_LENGTH;
}

/** Редактируемый вариант: в поле держим только цифры (слитно). */
function parseTyped(text: string): string {
  return binIinDigits(text);
}

export interface BinIinInputProps
  extends Omit<
    React.ComponentProps<'input'>,
    'value' | 'onChange' | 'type' | 'maxLength' | 'inputMode'
  > {
  value: string;
  /** Получает строку из цифр (или `''`, если поле очистили). */
  onChange: (value: string) => void;
}

export const BinIinInput: React.FC<BinIinInputProps> = ({
  value,
  onChange,
  className,
  placeholder = '123456789012',
  disabled,
  readOnly,
  ...rest
}) => {
  const digits = binIinDigits(value);

  const handleChange = React.useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      onChange(parseTyped(event.target.value));
    },
    [onChange],
  );

  // Вставку обрабатываем отдельно: браузер обрезал бы её по maxLength,
  // и вставленный БИН/ИИН с разделителями потерял бы хвост.
  const handlePaste = React.useCallback(
    (event: React.ClipboardEvent<HTMLInputElement>) => {
      if (readOnly || disabled) return;
      const pasted = event.clipboardData.getData('text');
      if (!pasted.trim()) return;
      event.preventDefault();
      onChange(parseTyped(pasted));
    },
    [onChange, readOnly, disabled],
  );

  return (
    <Input
      {...rest}
      type="text"
      inputMode="numeric"
      autoComplete="off"
      value={digits}
      onChange={handleChange}
      onPaste={handlePaste}
      placeholder={placeholder}
      maxLength={KZ_BIN_IIN_LENGTH}
      disabled={disabled}
      readOnly={readOnly}
      className={cn('font-mono', className)}
    />
  );
};

export default BinIinInput;
