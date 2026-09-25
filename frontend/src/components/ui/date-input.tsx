import * as React from 'react';
import { Calendar } from 'lucide-react';

import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';

/**
 * Дата с маской `дд.мм.гггг` — и с календарём.
 *
 * Зачем не голый `<input type="date">`, который стоял тут раньше: он выглядит
 * полем с подсказкой «дд.мм.гггг», но набор в нём посегментный и ведёт себя
 * по-разному в разных браузерах, а несуществующую дату (31.02) он молча
 * НЕ отдаёт — значение остаётся пустым, и человек видит пустое поле вместо
 * объяснения. Здесь набор обычный: цифры, точки ставятся сами, а разбор один
 * на все браузеры.
 *
 * Календарь при этом никуда не делся: кнопка справа открывает системный
 * выбор через `showPicker()` у скрытого `type="date"`. Отдельная библиотека
 * не нужна — в бандле её и нет (`components/ui/calendar.tsx` ни одной
 * страницей не импортируется), а бюджет размера бандла проверяется на сборке.
 *
 * Наружу (`onChange`) уходит ISO `ГГГГ-ММ-ДД` — формат, который ждут и
 * бэкенд, и остальная форма; пока дата не дособрана, уходит `''`. Про
 * НЕДОПИСАННУЮ и про несуществующую дату форма узнаёт из `onValidityChange`:
 * пустое поле — это не ошибка, а «13.13.2026» — ошибка, и различать их
 * по одному только `value` нельзя.
 */

/** Границы разумного: опечатка в годе («20226») не должна проходить молча. */
export const MIN_YEAR = 1900;
export const MAX_YEAR = 2100;

/** Только цифры, максимум восемь: ддммгггг. */
function digitsOf(text: string): string {
  return text.replace(/\D/g, '').slice(0, 8);
}

/** `01022026` → `01.02.2026`; недописанное форматируется как есть. */
export function maskDate(text: string): string {
  const digits = digitsOf(text);
  const parts = [digits.slice(0, 2), digits.slice(2, 4), digits.slice(4, 8)];
  return parts.filter((part) => part.length > 0).join('.');
}

/** Существует ли такая дата в календаре: 31.02 и 13-й месяц отсекаются. */
function isRealDate(day: number, month: number, year: number): boolean {
  if (year < MIN_YEAR || year > MAX_YEAR) return false;
  const probe = new Date(year, month - 1, day);
  return probe.getFullYear() === year
    && probe.getMonth() === month - 1
    && probe.getDate() === day;
}

/** `дд.мм.гггг` → `ГГГГ-ММ-ДД`, либо `null` (недописано или не существует). */
export function toIsoDate(text: string): string | null {
  const digits = digitsOf(text);
  if (digits.length < 8) return null;
  const day = Number(digits.slice(0, 2));
  const month = Number(digits.slice(2, 4));
  const year = Number(digits.slice(4, 8));
  if (!isRealDate(day, month, year)) return null;
  return `${digits.slice(4, 8)}-${digits.slice(2, 4)}-${digits.slice(0, 2)}`;
}

/** `ГГГГ-ММ-ДД` → `дд.мм.гггг` для показа в поле. */
export function fromIsoDate(iso: string | null | undefined): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso ?? ''));
  return match ? `${match[3]}.${match[2]}.${match[1]}` : '';
}

export interface DateInputProps
  extends Omit<
    React.ComponentProps<'input'>,
    'value' | 'onChange' | 'type' | 'inputMode' | 'maxLength'
  > {
  /** ISO `ГГГГ-ММ-ДД` или `''`. */
  value: string;
  /** Получает ISO `ГГГГ-ММ-ДД`, либо `''`, пока дата не дособрана. */
  onChange: (value: string) => void;
  /**
   * Сообщает, что в поле НЕВЕРНАЯ дата: набрано что-то, но собрать из этого
   * дату нельзя. Пустое поле неверным не считается — обязательность решает
   * форма, а не поле ввода.
   */
  onValidityChange?: (invalid: boolean) => void;
  invalid?: boolean;
}

export const DateInput: React.FC<DateInputProps> = ({
  value,
  onChange,
  onValidityChange,
  invalid,
  className,
  disabled,
  readOnly,
  id,
  // Границы — только для календаря: текстовое поле их не понимает, а
  // проверку набранного руками всё равно делает форма.
  min,
  max,
  ...rest
}) => {
  const [text, setText] = React.useState(() => fromIsoDate(value));
  const pickerRef = React.useRef<HTMLInputElement>(null);
  /** Последнее, что отдали наружу сами: по нему отличается чужая правка. */
  const emitted = React.useRef(value);

  // Значение сменили СНАРУЖИ (сброс формы, открыли другую карточку) — только
  // тогда и перерисовываем текст. Свои же изменения игнорируем: пока дата не
  // дособрана, наружу уходит `''`, и «синхронизация» затёрла бы набранное.
  // Именно так съедался первый символ при перепечатывании готовой даты.
  React.useEffect(() => {
    if (value === emitted.current) return;
    emitted.current = value;
    setText(fromIsoDate(value));
  }, [value]);

  const apply = (next: string) => {
    const masked = maskDate(next);
    setText(masked);
    const iso = toIsoDate(masked) ?? '';
    emitted.current = iso;
    onChange(iso);
    onValidityChange?.(masked.length > 0 && iso === '');
  };

  return (
    <div className="relative">
      <Input
        {...rest}
        id={id}
        value={text}
        inputMode="numeric"
        maxLength={10}
        placeholder="дд.мм.гггг"
        disabled={disabled}
        readOnly={readOnly}
        aria-invalid={invalid || undefined}
        onChange={(event) => apply(event.target.value)}
        className={cn('pr-9', invalid && 'border-destructive', className)}
      />
      {/* Скрытое поле существует только ради системного календаря: свой
          рисовать незачем, а `showPicker()` требует настоящий input. */}
      <input
        ref={pickerRef}
        type="date"
        tabIndex={-1}
        aria-hidden
        className="pointer-events-none absolute h-0 w-0 opacity-0"
        value={value}
        min={min}
        max={max}
        onChange={(event) => apply(fromIsoDate(event.target.value))}
      />
      <button
        type="button"
        tabIndex={-1}
        disabled={disabled || readOnly}
        aria-label="Открыть календарь"
        className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground
          hover:text-foreground disabled:pointer-events-none disabled:opacity-50"
        onClick={() => {
          const picker = pickerRef.current;
          // showPicker() есть не везде; там, где его нет, кнопка просто
          // возвращает фокус в поле — набрать дату руками можно всегда.
          if (picker && typeof picker.showPicker === 'function') picker.showPicker();
        }}
      >
        <Calendar className="h-4 w-4" />
      </button>
    </div>
  );
};

export default DateInput;
