/**
 * Длины и диапазоны полей — те же, что в схемах бэкенда.
 *
 * Смысл в том, чтобы неверное просто не вводилось: `maxLength` не даёт
 * набрать 300-й символ, `min`/`max` у числа — выйти за диапазон. Это дешевле
 * любой проверки, потому что ошибки не возникает вовсе.
 *
 * ⚠️ Зеркало, а не источник истины. Источник — `Field(...)` в
 * `apps/<домен>/schemas.py`, и рядом с каждой строкой указано, откуда она
 * взята. Разъедутся — сервер всё равно откажет, и человек увидит причину
 * (`reportApiError`), так что цена расхождения — лишний запрос, а не потеря
 * данных. Поэтому зеркалим ТОЛЬКО поля, где промах реален: длинное название,
 * грейд из головы, отрицательный вес.
 */

/** apps/hr/schemas.py */
export const HR_LIMITS = {
  /** EmployeeCreate.first_name / last_name / middle_name */
  personName: 100,
  /** EmployeeCreate.email */
  email: 255,
  /** DepartmentCreate.name, PositionCreate.title */
  title: 255,
  /** PositionCreate.grade */
  grade: { min: 1, max: 10 },
  /** PositionCreate.weight */
  weight: { min: 0 },
} as const;

/** apps/tasks/schemas.py */
export const TASKS_LIMITS = {
  /** ProjectCreate.name, SiteCreate.name */
  name: 200,
  /** SiteBlockCreate.name */
  blockName: 120,
  /** SiteCreate.code, SiteBlockCreate.code */
  code: 32,
  /** SiteCreate.region */
  region: 120,
  /** ContractorCreate.name */
  contractorName: 255,
  /** ContractorCreate.short_name */
  shortName: 100,
  /** ContractorCreate.contact_person */
  contactPerson: 200,
  /** SiteBlockCreate.order */
  order: { min: 0, max: 32767 },
  /** описания и заметки: SiteCreate.description, ContractorCreate.notes */
  longText: 5000,
} as const;
