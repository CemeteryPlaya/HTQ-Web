/**
 * api/signoff.ts
 * Клиент универсального согласования (`/api/signoff/v1`).
 *
 * Пути без завершающего слэша — бэкенд регистрирует оба написания
 * (APPEND_SLASH=False); придерживаемся одного стиля, как в api/contracts.ts.
 *
 * **Чего здесь намеренно нет — запуска процесса.** `POST /processes`
 * существует, но принимает `subject_id` ЛЮБОГО типа и потому обходит
 * доменные права мимо их владельца; на бэкенде он администраторский и
 * оставлен операторским инструментом. Штатная отправка на согласование —
 * эндпоинт предметной аппки (`contractsApi.submitBudget` и соседи).
 */

import api from './client';
import { apiPath } from './endpoints';
import type {
  ApprovalProcess,
  ApprovalRoute,
  DecisionInput,
  InboxItem,
  ProcessTask,
  ReworkInput,
  RouteStage,
  SignoffEnums,
  StageInput,
  StageUpdateInput,
  Subject,
} from '@/types/signoff';

const path = (suffix: string) => apiPath('signoff', suffix);

export interface ProcessListParams {
  subject_type?: string;
  subject_id?: number;
  state?: string;
  initiator_id?: number;
}

export const signoffApi = {
  // ─── Справочное ────────────────────────────────────────────────────────
  getEnums: () => api.get<SignoffEnums>(path('enums')),
  /** Что вообще согласуемо — реестр, наполненный предметными аппками.
   *  Вместе с типом приходят его `fields` — факты, по которым разрешено
   *  ветвить маршрут, со справочниками значений. Отсюда редактор и узнаёт,
   *  что у бюджета бывает «страна администратора» и какие страны есть. */
  listSubjects: () => api.get<Subject[]>(path('subjects')),

  // ─── Маршруты ──────────────────────────────────────────────────────────
  listRoutes: (params?: { subject_type?: string; is_active?: boolean }) =>
    api.get<ApprovalRoute[]>(path('routes'), { params }),
  getRoute: (id: number) => api.get<ApprovalRoute>(path(`routes/${id}`)),
  createRoute: (data: { subject_type: string; name: string; is_active?: boolean }) =>
    api.post<ApprovalRoute>(path('routes'), data),
  updateRoute: (id: number, data: { name?: string; is_active?: boolean }) =>
    api.patch<ApprovalRoute>(path(`routes/${id}`), data),
  deleteRoute: (id: number) => api.delete(path(`routes/${id}`)),

  // ─── Этапы маршрута ────────────────────────────────────────────────────
  /** Согласующие передаются вместе с этапом: этап без них движок не
   *  запустит, и заводить его отдельно значило бы штатно проходить через
   *  заведомо нерабочее состояние. */
  addStage: (routeId: number, data: StageInput) =>
    api.post<RouteStage>(path(`routes/${routeId}/stages`), data),
  getStage: (id: number) => api.get<RouteStage>(path(`stages/${id}`)),
  updateStage: (id: number, data: StageUpdateInput) =>
    api.patch<RouteStage>(path(`stages/${id}`), data),
  deleteStage: (id: number) => api.delete(path(`stages/${id}`)),

  // ─── Процессы ──────────────────────────────────────────────────────────
  listProcesses: (params?: ProcessListParams) =>
    api.get<ApprovalProcess[]>(path('processes'), { params }),
  getProcess: (id: number) => api.get<ApprovalProcess>(path(`processes/${id}`)),
  /** Отзыв — инициатором или администратором; право проверяется по строке.
   *  Отзыв ≠ отказ: объект возвращается в `draft` и может быть отправлен
   *  снова. */
  cancelProcess: (id: number) =>
    api.post<ApprovalProcess>(path(`processes/${id}/cancel`)),
  /**
   * Вернуть на доработку объект по УЖЕ ЗАКРЫТОМУ кругу — согласующим этого
   * процесса или администратором.
   *
   * Единственный способ отпереть согласованный или отклонённый объект: оба
   * заперты для правки (`isEditableState`). Пока согласование ИДЁТ, вызов
   * ответит 409 — там та же операция делается решением
   * `decide(taskId, { decision: 'rework' })`, а инициатору доступен отзыв.
   */
  reworkProcess: (id: number, data: ReworkInput = {}) =>
    api.post<ApprovalProcess>(path(`processes/${id}/rework`), data),

  // ─── Решения ───────────────────────────────────────────────────────────
  /** Персональная очередь спрашивающего. Чужую бэкенд не отдаёт ни по
   *  какому параметру — для надзора есть `listProcesses`. */
  inbox: () => api.get<InboxItem[]>(path('tasks/mine')),
  /** Решает НАЗВАННЫЙ в маршруте человек, а не тот, у кого есть админский
   *  флаг: админский токен на чужой задаче получит 409. */
  decide: (taskId: number, data: DecisionInput) =>
    api.post<ApprovalProcess>(path(`tasks/${taskId}/decision`), data),
  /**
   * Приложить документ к своему запросу — ДО решения, отдельным запросом.
   *
   * Так устроен и бэкенд: загрузка в объектное хранилище не должна идти
   * внутри транзакции, держащей блокировку процесса. Порядок для клиента,
   * соответственно, всегда «сначала `attachDocument`, потом `decide`» —
   * иначе решение отобьётся 409 «сначала загрузите PDF».
   *
   * Только PDF (проверяет media_files по magic-байтам, переименованный файл
   * не пройдёт) и только тот, кому адресован запрос: администраторского
   * исключения здесь нет.
   */
  attachDocument: (taskId: number, file: File) => {
    const form = new FormData();
    form.append('file', file);
    // Content-Type не задаём: boundary проставит браузер сам.
    return api.post<ProcessTask>(path(`tasks/${taskId}/attachment`), form);
  },
};
