import type { PrefillFieldDiff, PrefillPreview } from '@/types/hr';

/**
 * Чистая часть диалога «подтянуть данные» — то, что решает, ЧТО будет
 * отмечено и как поле называется. Вынесено из компонента, потому что именно
 * здесь живёт обещание задачи: заполненное поле не перезаписывается молча.
 */

/**
 * Подпись поля. Ключи переиспользуют уже существующие
 * `hr.pages.employees.fields.*` — в форме сотрудника те же поля называются
 * ровно так, и предпросмотр не должен придумывать им вторые имена.
 */
export const PREFILL_FIELD_LABEL_KEYS: Record<string, string> = {
  last_name: 'hr.pages.employees.fields.lastName',
  first_name: 'hr.pages.employees.fields.firstName',
  middle_name: 'hr.pages.employees.fields.patronymic',
  email: 'hr.pages.employees.fields.email',
  phone: 'hr.pages.employees.fields.phone',
  department_id: 'hr.pages.employees.fields.department',
  position_id: 'hr.pages.employees.fields.position',
  avatar_url: 'hr.pages.employees.prefill.fields.avatar',
  bio: 'hr.pages.employees.fields.notes',
  user_id: 'hr.pages.employees.fields.user',
};

/**
 * Что отмечено при открытии предпросмотра.
 *
 * Пустые поля — да: заполнить пустое ничего не разрушает, и заставлять
 * человека отмечать восемь галочек ради этого незачем. Расхождения — нет:
 * их разрешает человек, а не умолчание. Совпадающие не отмечаются никогда —
 * применять там нечего.
 */
export const defaultSelection = (fields: PrefillFieldDiff[]): string[] =>
  fields.filter((row) => row.state === 'fill').map((row) => row.field);

/** Совпадающие строки показываются, но выбрать их нельзя. */
export const isSelectable = (row: PrefillFieldDiff): boolean => row.state !== 'same';

/**
 * Значения для формы создания сотрудника: только отмеченное.
 *
 * Диалог в режиме создания ничего не сохраняет — он возвращает значения в
 * форму, и человек ещё увидит их перед отправкой.
 */
export const pickValues = (
  preview: PrefillPreview,
  selected: string[],
): Record<string, string | number> => {
  const chosen = new Set(selected);
  const out: Record<string, string | number> = {};
  preview.fields.forEach((row) => {
    if (chosen.has(row.field) && isSelectable(row) && row.incoming !== null) {
      out[row.field] = row.incoming;
    }
  });
  return out;
};

/** Порядок вкладок-источников — от самого частого к редкому. */
export const PREFILL_SOURCE_TYPES = ['user', 'employee', 'mailbox'] as const;


/**
 * Стоит ли вообще спрашивать сервер о совпадении.
 *
 * Подсказка срабатывает, только когда набрано что-то опознающее: почта с
 * доменом, телефон достаточной длины (тот же порог, что у бэкенда —
 * `htqweb/phone.py::MIN_DIGITS`) или имя И фамилия целиком. Иначе она
 * превращается в поток совпадений по одной букве фамилии, а на пустой форме —
 * в выгрузку справочника.
 */
export const matchQueryIsAnswerable = (
  { email, phone, firstName, lastName }: {
    email: string; phone: string; firstName: string; lastName: string;
  },
): boolean => {
  if (email.includes('@') && (email.split('@')[1]?.length ?? 0) > 1) return true;
  if (phone.replace(/\D/g, '').length >= 7) return true;
  return firstName.trim().length >= 2 && lastName.trim().length >= 2;
};
