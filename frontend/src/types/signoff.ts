/**
 * types/signoff.ts
 * Типы универсального согласования (backend: apps.signoff, `/api/signoff/v1`).
 *
 * **Не путать с `types/requests` (apps.approvals).** Тот домен согласует
 * СВОИ `RequestInstance` — строки с JSON-значениями формы, которую он же и
 * спроектировал. Этот согласует строку в ЧУЖОЙ таблице, адресуя её парой
 * `(subject_type, subject_id)` — например `"contracts.budget"` + pk.
 * Пересечений в типах между ними нет и быть не должно.
 *
 * Заголовок и ссылку на предметный объект (`subject_title`/`subject_url`)
 * строит его собственная аппка через колбэк `describe` — движок их не
 * выдумывает и может вернуть `null`, если тип больше не зарегистрирован.
 */

/** Пара value/label из `GET /enums` — подписи берём с бэкенда, а не из
 *  своего словаря, иначе они разойдутся с моделью при первой же правке. */
export interface EnumOption {
  value: string;
  label: string;
}

/** Сколько согласующих этапа должны одобрить, чтобы этап прошёл. */
export type Quorum = 'any' | 'all';

export type ProcessState = 'pending' | 'approved' | 'rejected' | 'cancelled';

/** `skipped` — этап, до которого дело не дошло (процесс отклонили или
 *  отозвали раньше). Отдельно от `rejected`, чтобы в карточке было видно,
 *  кто отказал, а кто просто не успел получить запрос. */
export type StageState = 'waiting' | 'active' | 'approved' | 'rejected' | 'skipped';

export type TaskState = 'pending' | 'approved' | 'rejected' | 'skipped';

/**
 * Состояние согласования ПРЕДМЕТНОГО объекта (колонка `approval_state`,
 * примесь `signoff.Approvable`). Совпадает с `ProcessState` не полностью:
 * у объекта есть «черновик», которого у процесса быть не может, а
 * отозванный процесс возвращает объект в `draft` — отправить снова можно.
 */
export type ApprovalState = 'draft' | 'pending' | 'approved' | 'rejected';

// ─── Маршруты ────────────────────────────────────────────────────────────

export interface Approver {
  user_id: number;
  /** Разворачивается бэкендом через apps.users — показывать надо человека. */
  full_name: string;
  is_active: boolean;
}

export interface RouteStage {
  id: number;
  /** Этапы с ОДИНАКОВЫМ order идут параллельно, с разным — последовательно.
   *  Вся параллельность выражена этим числом, отдельной модели графа нет. */
  order: number;
  name: string;
  quorum: Quorum;
  approvers: Approver[];
}

export interface ApprovalRoute {
  id: number;
  subject_type: string;
  name: string;
  /** Активный маршрут на тип ровно один — частичный уникальный индекс. */
  is_active: boolean;
  stages: RouteStage[];
  created_at: string;
  updated_at: string;
}

/** Согласуемый тип из реестра — то, из чего выбирает конструктор маршрута.
 *  Список наполняют сами предметные аппки на старте, захардкодить его
 *  нельзя. */
export interface Subject {
  subject_type: string;
  label: string;
  has_active_route: boolean;
}

// ─── Процессы ────────────────────────────────────────────────────────────

export interface ProcessTask {
  id: number;
  user_id: number;
  full_name: string;
  state: TaskState;
  comment: string;
  acted_at: string | null;
}

export interface ProcessStage {
  id: number;
  order: number;
  name: string;
  quorum: Quorum;
  state: StageState;
  decided_at: string | null;
  tasks: ProcessTask[];
}

export interface ApprovalProcess {
  id: number;
  subject_type: string;
  subject_id: number;
  state: ProcessState;
  initiator_id: number | null;
  /** Какая группа этапов сейчас на рассмотрении. */
  current_order: number | null;
  created_at: string;
  finished_at: string | null;
  /** Снимок маршрута на момент запуска: правка маршрута не трогает
   *  уже идущие согласования. */
  stages: ProcessStage[];
  subject_title: string | null;
  subject_url: string | null;
}

/** Строка списка «ждёт моего решения». */
export interface InboxItem {
  task_id: number;
  process_id: number;
  subject_type: string;
  subject_id: number;
  subject_title: string | null;
  subject_url: string | null;
  stage_name: string;
  quorum: Quorum;
  initiator_id: number | null;
  created_at: string;
}

export interface SignoffEnums {
  quorum: EnumOption[];
  process_state: EnumOption[];
  stage_state: EnumOption[];
  task_state: EnumOption[];
}

// ─── Запросы ─────────────────────────────────────────────────────────────

export interface StageInput {
  order: number;
  name: string;
  quorum: Quorum;
  /** Минимум один — этап без согласующих движок не запустит. */
  approver_ids: number[];
}

/** PATCH этапа: `approver_ids` заменяет список ЦЕЛИКОМ, а его отсутствие
 *  оставляет согласующих в покое. Не путать одно с другим. */
export interface StageUpdateInput {
  order?: number;
  name?: string;
  quorum?: Quorum;
  approver_ids?: number[];
}

export interface DecisionInput {
  decision: 'approve' | 'reject';
  comment?: string;
}
