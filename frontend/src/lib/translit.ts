/**
 * Кириллица → латиница и корпоративный адрес из имени.
 *
 * Таблица — зеркало серверной (`apps/mail/services/mailbox_service.py::_TRANSLIT`,
 * та же таблица продублирована в `apps/hr/services/department_service.py`).
 * Копия здесь неизбежна: адрес подставляется в форму по мере набора имени, и
 * ходить за ним на сервер на каждое нажатие клавиши нельзя. Цена копии —
 * сторож `translit.test.ts`, который сверяет обе таблицы посимвольно: разъехавшись,
 * они дали бы адрес, не совпадающий с реальным ящиком, а заметили бы это уже
 * на почтовом сервере.
 *
 * Правило сборки — `first.last`, тот же шаблон, что у
 * `mailbox_service.autogen_local_part` (там он настраиваемый, потому что
 * соглашение об именовании у каждой компании своё; здесь — подсказка в форме,
 * которую человек волен переписать).
 */

export const TRANSLIT_MAP: Record<string, string> = {
  а: 'a', б: 'b', в: 'v', г: 'g', д: 'd', е: 'e', ё: 'e',
  ж: 'zh', з: 'z', и: 'i', й: 'y', к: 'k', л: 'l', м: 'm',
  н: 'n', о: 'o', п: 'p', р: 'r', с: 's', т: 't', у: 'u',
  ф: 'f', х: 'h', ц: 'ts', ч: 'ch', ш: 'sh', щ: 'shch',
  ъ: '', ы: 'y', ь: '', э: 'e', ю: 'yu', я: 'ya',
};

/** Побуквенная транслитерация; неизвестные символы остаются как есть. */
export const translit = (value: string): string =>
  [...value.toLowerCase()].map((char) => TRANSLIT_MAP[char] ?? char).join('');

/** Транслитерация + отсечение всего, что не буква и не цифра. */
export const slug = (value: string): string =>
  translit(value).replace(/[^a-z0-9]+/g, '');

/**
 * Почтовый домен компании.
 *
 * Значение по умолчанию — не подмена в смысле `lib/fallback.ts`, а обычный
 * дефолт конфигурации: авторитетный домен ЯЩИКОВ живёт на сервере
 * (`CORPORATE_MAIL_DOMAIN`), а здесь собирается лишь предложение для поля,
 * которое видно человеку и правится им до отправки.
 */
export const CORPORATE_MAIL_DOMAIN: string =
  import.meta.env.VITE_CORPORATE_MAIL_DOMAIN || 'htq.group';

/**
 * `Санжар` + `Инамжанов` → `sanzhar.inamzhanov`.
 *
 * Одно из имён пустое — берётся то, что есть: шаблон `first.last` к одному
 * имени неприменим, а точка на краю дала бы битый адрес.
 */
export const emailLocalPart = (firstName: string, lastName: string): string => {
  const first = slug(firstName);
  const last = slug(lastName);
  if (!first || !last) return first || last;
  return `${first}.${last}`;
};

/**
 * Корпоративный адрес из имени и фамилии, или пустая строка.
 *
 * Пустая — намеренно: сервер в такой ситуации подставляет `user`, потому что
 * ящик обязан иметь локальную часть, а поле формы — нет. Показать человеку
 * `user@htq.group` значило бы предложить заведомо неверный адрес, который
 * легко отправить не глядя.
 */
export const corporateEmail = (
  firstName: string,
  lastName: string,
  domain: string = CORPORATE_MAIL_DOMAIN,
): string => {
  const local = emailLocalPart(firstName, lastName);
  return local ? `${local}@${domain}` : '';
};

/**
 * Подставить корпоративный адрес в форму — пока его не правили руками.
 *
 * Второй аргумент обязателен и не имеет умолчания намеренно: соглашение
 * `имя.фамилия` покрывает не всех (однофамильцы, двойные имена, внешние
 * подрядчики), и перебивать ручной ввод «умной» догадкой — худший вид помощи.
 * Забыть про этот флаг проще всего, поэтому его приходится передать явно.
 */
export const withSuggestedEmail = <
  T extends { first_name: string; last_name: string; email: string },
>(
  form: T,
  emailEdited: boolean,
): T => (emailEdited
  ? form
  : { ...form, email: corporateEmail(form.first_name, form.last_name) });
