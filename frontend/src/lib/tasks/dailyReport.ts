/**
 * Правила доступа к ежедневному отчёту — дубль серверных проверок.
 *
 * Оригиналы: `views._report_for_write` (правка отчёта) и
 * `task_service.can_progress` (заведение отчёта и плановый объём — оба под
 * `require_soft_edit`). Копия на фронте нужна, чтобы не показывать кнопку,
 * которая заведомо даст 403, — но копия серверного правила обязана быть
 * покрыта тестом, иначе она разъедется с оригиналом молча, и «сломанная
 * кнопка» вернётся с другой стороны.
 */
import type { Task } from '@/types/tasks';

export interface ReportEditRights {
  /** Автор отчёта (`DailyReport.author_id`). */
  authorId: number | null;
  /** Супервайзер задачи. `undefined` — вызывающий его не знает. */
  supervisorId?: number | null;
  /** Текущий пользователь. `NaN`/`null`, если профиль ещё не загрузился. */
  myId: number | null;
  /** staff или superuser. */
  elevated: boolean;
}

/**
 * Кто может править и удалять отчёт: автор, супервайзер задачи, админ.
 *
 * Обычный участник задачи сюда НЕ попадает, хотя заводить свой отчёт вправе:
 * цифра выполнения — основание для расчётов, и править её за коллегу не то
 * же самое, что отчитаться самому.
 *
 * Неизвестный `supervisorId` (страница не знает супервайзера) трактуется как
 * «не он»: выдать право по отсутствующему значению значило бы показать кнопку
 * там, где сервер откажет.
 */
export const canEditDailyReport = (
  { authorId, supervisorId, myId, elevated }: ReportEditRights,
): boolean => {
  if (elevated) return true;
  if (myId === null || Number.isNaN(myId)) return false;
  return authorId === myId || (supervisorId ?? null) === myId;
};

/** Поля задачи, которых достаточно для правила «мягкой правки». */
type SoftEditTask = Pick<Task,
  'reporter' | 'supervisor' | 'assignee' | 'assignees'> &
  Partial<Pick<Task, 'delegates'>>;

/**
 * Кто вправе отчитаться о задаче и задать её плановый объём.
 *
 * Зеркало `task_service.can_progress`: админ, автор задачи (`reporter`),
 * супервайзер, его делегат — и ЛЮБОЙ исполнитель, включая соисполнителей из
 * `assignees`. Оба действия под одним серверным правом не случайно:
 * «развезли 180 из 250» — это отчёт о ходе работ, ровно то же, что
 * `progress_percent`, а плановый объём без права его завести делает отчёт
 * невозможным.
 */
export const canReportOnTask = (
  task: SoftEditTask | null | undefined,
  myId: number | null,
  elevated: boolean,
): boolean => {
  if (elevated) return true;
  if (!task || myId === null || Number.isNaN(myId)) return false;
  if (task.reporter === myId || task.supervisor === myId) return true;
  if (task.assignee === myId) return true;
  if ((task.assignees ?? []).some((row) => row.user_id === myId)) return true;
  return (task.delegates ?? []).some((row) => row.user_id === myId);
};

export default canEditDailyReport;
