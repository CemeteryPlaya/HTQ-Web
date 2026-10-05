/**
 * Ключ объекта согласования.
 *
 * signoff хранит и отдаёт его строкой (`ApprovalProcess.subject_id`):
 * документы модуля БЗО адресуются UUID. Предметные экраны старых доменов
 * по-прежнему держат целые id — компоненты signoff принимают оба вида.
 */
export type SubjectId = number | string;

/**
 * Можно ли уже спрашивать процессы объекта. Целый ключ — конечное число
 * (`Number(params.id)` даёт NaN, пока маршрут не разобран); строковый —
 * непустая строка. `Number.isFinite` для UUID всегда `false`, поэтому
 * одной им проверкой обойтись нельзя.
 */
export const isSubjectIdReady = (id: SubjectId): boolean =>
  typeof id === 'string' ? id.trim() !== '' : Number.isFinite(id);
