/**
 * Редактор условия этапа — «этап нужен, если {поле} {оператор} {значение}».
 *
 * **Ничего не знает о предметных аппках.** Поля и справочники значений
 * приходят готовыми из `GET /subjects` (`SubjectField[]`), а туда попадают из
 * `fact_fields()` предметной аппки. Поэтому здесь нет ни слова про страны и
 * бюджеты: новый согласуемый тип со своими полями появляется без правок в
 * этом файле.
 *
 * **Плоский список предикатов, соединённых И** — ровно то, что умеет бэкенд
 * (`apps/signoff/services/conditions.py`). Вложенности и ИЛИ между полями
 * здесь нет намеренно: ИЛИ по одному полю — это оператор «одно из», по
 * разным полям — два этапа в одной группе.
 */

import { Plus, X } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import type {
  Condition,
  ConditionOp,
  Predicate,
  SubjectField,
} from '@/types/signoff';

// Подписи операторов и однострочный рендер условия живут в format.ts — это
// данные и чистая функция, и в одном файле с компонентом они ломали бы fast
// refresh (та же причина, по которой labels.ts отделён от states.tsx).
import { OP_LABELS } from './format';

const SET_OPS: ConditionOp[] = ['in', 'not_in'];
const ORDER_OPS: ConditionOp[] = ['gt', 'gte', 'lt', 'lte'];

/** Какие операторы осмысленны для поля этого типа.
 *
 *  Повторяет ограничения `conditions._validate_value`: справочник нельзя
 *  сравнивать «больше/меньше», у да/нет осмысленно только равенство. Список
 *  сужается здесь, чтобы недопустимую пару нельзя было и выбрать, — 409 от
 *  бэкенда остаётся страховкой, а не основным способом об этом узнать. */
function opsFor(field: SubjectField | undefined): ConditionOp[] {
  if (!field) return ['eq'];
  if (field.type === 'choice') return ['in', 'not_in', 'eq'];
  if (field.type === 'bool') return ['eq'];
  if (field.type === 'number') return ['eq', ...ORDER_OPS, 'in', 'not_in'];
  return ['eq', 'in', 'not_in', ...ORDER_OPS];
}

/** Значение по умолчанию при смене поля или оператора.
 *
 *  Считается заново, а не переносится: у «одно из» значение — массив, у
 *  «равно» — скаляр, и перенос между ними даёт предикат, который бэкенд не
 *  примет. */
function defaultValue(field: SubjectField | undefined, op: ConditionOp): unknown {
  if (SET_OPS.includes(op)) return [];
  if (field?.type === 'bool') return true;
  if (field?.type === 'number') return 0;
  if (field?.type === 'choice') return field.options[0]?.value ?? null;
  return '';
}

interface ValueEditorProps {
  field: SubjectField | undefined;
  op: ConditionOp;
  value: unknown;
  onChange: (value: unknown) => void;
}

/** Виджет значения — по типу поля, а не по оператору. */
const ValueEditor = ({ field, op, value, onChange }: ValueEditorProps) => {
  const multiple = SET_OPS.includes(op);

  // Справочник: значения выбираются кликом. Свободного ввода здесь нет —
  // id, которого нет в справочнике, бэкенд отвергнет, и набирать его руками
  // означало бы предлагать заведомо неверный путь.
  if (field?.type === 'choice') {
    const selected = multiple
      ? ((value as unknown[]) ?? [])
      : [value].filter((item) => item !== null && item !== undefined);

    const toggle = (option: unknown) => {
      if (!multiple) return onChange(option);
      const next = selected.includes(option)
        ? selected.filter((item) => item !== option)
        : [...selected, option];
      onChange(next);
    };

    return (
      <div className="flex flex-wrap gap-1.5">
        {field.options.map((option) => {
          const active = selected.includes(option.value);
          return (
            <button
              key={String(option.value)}
              type="button"
              onClick={() => toggle(option.value)}
              className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-full"
            >
              <Badge
                variant={active ? 'default' : 'outline'}
                className={cn('cursor-pointer', !active && 'text-muted-foreground')}
              >
                {option.label}
              </Badge>
            </button>
          );
        })}
        {field.options.length === 0 && (
          <span className="text-xs text-muted-foreground">
            Справочник пуст — выбирать нечего.
          </span>
        )}
      </div>
    );
  }

  if (field?.type === 'bool') {
    return (
      <Select
        value={value === true ? 'true' : 'false'}
        onValueChange={(next) => onChange(next === 'true')}
      >
        <SelectTrigger>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="true">да</SelectItem>
          <SelectItem value="false">нет</SelectItem>
        </SelectContent>
      </Select>
    );
  }

  // «Одно из» на числе или строке: значения перечисляются через запятую —
  // отдельный редактор списка ради редкого случая не окупается.
  if (multiple) {
    const asText = ((value as unknown[]) ?? []).join(', ');
    return (
      <Input
        value={asText}
        placeholder="через запятую"
        onChange={(event) => {
          const parts = event.target.value
            .split(',')
            .map((part) => part.trim())
            .filter(Boolean);
          onChange(
            field?.type === 'number' ? parts.map(Number).filter((n) => !Number.isNaN(n)) : parts,
          );
        }}
      />
    );
  }

  if (field?.type === 'number') {
    return (
      <Input
        type="number"
        value={value === null || value === undefined ? '' : String(value)}
        onChange={(event) => onChange(Number(event.target.value) || 0)}
      />
    );
  }

  return (
    <Input
      value={value === null || value === undefined ? '' : String(value)}
      onChange={(event) => onChange(event.target.value)}
    />
  );
};

interface ConditionEditorProps {
  fields: SubjectField[];
  value: Condition;
  onChange: (condition: Condition) => void;
  /** «Иначе» и собственное условие несовместимы — бэкенд такую пару не
   *  принимает, поэтому редактор при взведённом флаге просто выключается. */
  disabled?: boolean;
}

export const ConditionEditor = ({
  fields,
  value,
  onChange,
  disabled = false,
}: ConditionEditorProps) => {
  if (fields.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        Для этого типа объектов ветвление не настроено: аппка не объявила ни
        одного поля, по которому можно ветвить.
      </p>
    );
  }

  const fieldByKey = (key: string) => fields.find((field) => field.key === key);

  const update = (index: number, patch: Partial<Predicate>) => {
    const next = value.map((predicate, i) =>
      i === index ? { ...predicate, ...patch } : predicate,
    );
    onChange(next);
  };

  const add = () => {
    const field = fields[0];
    const op = opsFor(field)[0];
    onChange([...value, { field: field.key, op, value: defaultValue(field, op) }]);
  };

  if (value.length === 0) {
    return (
      <div className="space-y-1.5">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={add}
          disabled={disabled}
        >
          <Plus className="mr-1.5 h-3.5 w-3.5" />
          Добавить условие
        </Button>
        <p className="text-xs text-muted-foreground">
          Без условия этап нужен всегда.
        </p>
      </div>
    );
  }

  return (
    <div className={cn('space-y-2', disabled && 'pointer-events-none opacity-50')}>
      {value.map((predicate, index) => {
        const field = fieldByKey(predicate.field);
        const ops = opsFor(field);
        return (
          <div key={index} className="rounded-md border p-2.5 space-y-2">
            <div className="flex items-center gap-2">
              {index > 0 && (
                <Badge variant="outline" className="shrink-0 text-muted-foreground">
                  и
                </Badge>
              )}

              <Select
                value={predicate.field}
                onValueChange={(key) => {
                  const nextField = fieldByKey(key);
                  const nextOp = opsFor(nextField).includes(predicate.op)
                    ? predicate.op
                    : opsFor(nextField)[0];
                  update(index, {
                    field: key,
                    op: nextOp,
                    value: defaultValue(nextField, nextOp),
                  });
                }}
              >
                <SelectTrigger className="flex-1">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {fields.map((item) => (
                    <SelectItem key={item.key} value={item.key}>
                      {item.label || item.key}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              <Select
                value={predicate.op}
                onValueChange={(op) =>
                  update(index, {
                    op: op as ConditionOp,
                    value: defaultValue(field, op as ConditionOp),
                  })
                }
              >
                <SelectTrigger className="w-44 shrink-0">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {ops.map((op) => (
                    <SelectItem key={op} value={op}>
                      {OP_LABELS[op]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              <Button
                type="button"
                size="icon"
                variant="ghost"
                aria-label="Убрать условие"
                onClick={() => onChange(value.filter((_, i) => i !== index))}
              >
                <X className="h-4 w-4" />
              </Button>
            </div>

            <ValueEditor
              field={field}
              op={predicate.op}
              value={predicate.value}
              onChange={(next) => update(index, { value: next })}
            />

            {!field && (
              <p className="text-xs text-destructive">
                Поле «{predicate.field}» больше не существует — выберите другое,
                иначе запуск согласования по этому маршруту откажет.
              </p>
            )}
          </div>
        );
      })}

      <Button type="button" variant="outline" size="sm" onClick={add}>
        <Plus className="mr-1.5 h-3.5 w-3.5" />
        Ещё условие
      </Button>
    </div>
  );
};
