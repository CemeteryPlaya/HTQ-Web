/**
 * Адресация маршрута согласования заявки.
 *
 * Тип объекта один на все заявки, а маршрут — свой у каждого шаблона:
 * область маршрута (`ApprovalRoute.scope`) и есть шаблон. Формат строки
 * должен совпадать с бэкендом (`approvals/approval_hooks.py::scope_for_template`).
 */

export const REQUEST_SUBJECT_TYPE = 'approvals.request';

export function templateScope(templateId: number): string {
  return `template:${templateId}`;
}
