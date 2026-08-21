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

/**
 * Откуда берётся список согласующих этапа.
 *
 * `position` — HR-должности перечислены в маршруте, а их текущие сотрудники
 * разворачиваются на запуске. `initiator` — согласующий известен только на запуске: это тот, кто
 * отправил объект на согласование. Второй вариант вместе с
 * `requires_attachment` и есть «этап подписи»: автор подтверждает
 * согласованный остальными документ и прикладывает его PDF.
 *
 * Именно «инициатор», а не «автор документа»: движок не видит полей
 * предметной модели и разрешает того, кто нажал «на согласование». В
 * contracts это один и тот же человек по бизнес-процессу.
 */
export type ApproverKind = 'position' | 'initiator';

/**
 * Чем кончился круг согласования.
 *
 * `rework` — «возвращено на доработку». Круг закрывается так же, как на
 * отказе, но объект остаётся (точнее, СНОВА становится) правимым: см.
 * `ApprovalState`. Отказ значит «документ не годится», возврат — «поправьте
 * и пришлите снова».
 */
export type ProcessState = 'pending' | 'approved' | 'rejected' | 'rework' | 'cancelled';

/** `skipped` — этап, до которого дело не дошло (процесс отклонили, вернули
 *  на доработку или отозвали раньше). Отдельно от `rejected`, чтобы в
 *  карточке было видно, кто отказал, а кто просто не успел получить запрос. */
export type StageState =
  | 'waiting'
  | 'active'
  | 'approved'
  | 'rejected'
  | 'rework'
  | 'skipped';

export type TaskState = 'pending' | 'approved' | 'rejected' | 'rework' | 'skipped';

/**
 * Состояние согласования ПРЕДМЕТНОГО объекта (колонка `approval_state`,
 * примесь `signoff.Approvable`). Совпадает с `ProcessState` не полностью:
 * у объекта есть «черновик», которого у процесса быть не может, а
 * отозванный процесс возвращает объект в `draft` — отправить снова можно.
 *
 * Главное, что задаёт этот список, — ПРАВО ПРАВКИ (`isEditableState` ниже).
 * Заперты не только `pending`, но и `approved` с `rejected`: документ, под
 * которым принято решение, обязан остаться тем, каким его видели. Ключ
 * один — «вернуть на доработку».
 */
export type ApprovalState = 'draft' | 'pending' | 'approved' | 'rejected' | 'rework';

/**
 * Правится ли объект в этом состоянии — то же правило, что и на бэкенде
 * (`ApprovalState.editable()`), и то же обоснование белого списка: забытое
 * в нём состояние всего лишь запирает лишнее, а забытое в чёрном — молча
 * открывает документ, под которым уже стоят подписи.
 *
 * Фронтенду нужно, чтобы гасить кнопки правки ДО запроса; запрет всё равно
 * ставит бэкенд (409 `SubjectLocked`).
 */
export function isEditableState(state: ApprovalState): boolean {
  return state === 'draft' || state === 'rework';
}

// ─── Условные ветки ──────────────────────────────────────────────────────

/**
 * Оператор предиката. Список закрытый и совпадает с `conditions.OPS` на
 * бэкенде — вложенности, ИЛИ между полями и выражений тут нет намеренно:
 * ИЛИ по одному полю — это `in`, по разным — два этапа в одной группе.
 */
export type ConditionOp = 'eq' | 'in' | 'not_in' | 'gt' | 'gte' | 'lt' | 'lte';

/** `value` — скаляр для всех операторов, кроме `in`/`not_in` (там массив). */
export interface Predicate {
  field: string;
  op: ConditionOp;
  value: unknown;
}

/** Предикаты соединены И. Пустой список — «этап нужен всегда». */
export type Condition = Predicate[];

export interface FieldOption {
  value: unknown;
  label: string;
}

/**
 * Факт объекта, по которому разрешено ветвить маршрут.
 *
 * Список приходит из `GET /subjects` и целиком задаётся ПРЕДМЕТНОЙ аппкой
 * (`fact_fields()` в её `approval_hooks`): движок не знает, что такое
 * «страна администратора бюджета», он лишь передаёт сказанное. Поэтому
 * захардкодить эти поля во фронтенде нельзя — новый согласуемый тип
 * появляется без правок здесь.
 *
 * `options` заполнены только у `choice` — это справочник, и редактор рисует
 * по нему выпадающий список вместо поля ввода.
 */
export interface SubjectField {
  key: string;
  label: string;
  type: 'choice' | 'number' | 'string' | 'bool';
  options: FieldOption[];
}

/**
 * Значения справочника, под которые в группе не заведено ни одной ветки.
 *
 * Попади в эту дыру объект — запуск согласования откажет. Показывается
 * администратору в редакторе, чтобы дыру закрыл он, а не обнаружил через
 * месяц пользователь при отправке заявки.
 */
export interface CoverageGap {
  order: number;
  field: string;
  label: string;
  missing: FieldOption[];
}

// ─── Маршруты ────────────────────────────────────────────────────────────

export interface RouteRole {
  position_id: number;
  title: string;
  department_name: string | null;
  is_active: boolean;
}

export interface RouteStage {
  id: number;
  /** Этапы с ОДИНАКОВЫМ order идут параллельно, с разным — последовательно.
   *  Вся параллельность выражена этим числом, отдельной модели графа нет.
   *  Группа по order — она же и ветвление: см. `condition`. */
  order: number;
  name: string;
  quorum: Quorum;
  /** Пусто — этап нужен всегда. Иначе он попадёт в процесс только если
   *  условие сошлось на фактах объекта. */
  condition: Condition;
  /** «Иначе» для своей группы: этап идёт, только когда в группе не сошлось
   *  ни одно условие. С непустым `condition` не сочетается — бэкенд такую
   *  пару не принимает. */
  is_fallback: boolean;
  /** `initiator` — список `roles` пустой, и это норма: человек станет
   *  известен на запуске процесса. */
  approver_kind: ApproverKind;
  /** Согласовать этап можно только приложив PDF. На отказ не влияет. */
  requires_attachment: boolean;
  /** Согласовать этап можно только с непустым комментарием. Независимо от
   *  `requires_attachment` и `approver_kind` — комментарий можно требовать и
   *  от названного согласующего. На отказ/доработку не влияет. */
  requires_comment: boolean;
  roles: RouteRole[];
}

export interface ApprovalRoute {
  id: number;
  subject_type: string;
  name: string;
  /** Активный маршрут на тип ровно один — частичный уникальный индекс. */
  is_active: boolean;
  stages: RouteStage[];
  /** Только в карточке ОДНОГО маршрута (`GET /routes/:id`); в списке
   *  маршрутов поля нет — считать его на каждую строку слишком дорого. */
  coverage_gaps?: CoverageGap[];
  /** Тоже только в карточке одного маршрута: подпись инициатора стоит не в
   *  последней группе, и процесс завершится раньше, чем до неё дойдёт
   *  смысл. Предупреждение, а не запрет — бэкенд такой маршрут принимает. */
  initiator_stage_not_last?: boolean;
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
  /** Пусто — тип не поддерживает ветвление, условия ему не показываем. */
  fields: SubjectField[];
}

// ─── Процессы ────────────────────────────────────────────────────────────

export interface ProcessTask {
  id: number;
  user_id: number;
  full_name: string;
  state: TaskState;
  comment: string;
  acted_at: string | null;
  /** Документ, приложенный к этому решению (id в media_files). */
  file_id: string | null;
  /** Подписанная ссылка на него — короткоживущая, и её может не быть даже
   *  при непустом `file_id`, если media недоступен. */
  file_url: string | null;
}

export interface ProcessStage {
  id: number;
  order: number;
  name: string;
  quorum: Quorum;
  state: StageState;
  /** Снимок условия, по которому этап попал в процесс. */
  condition: Condition;
  /** Как этап попал в процесс. У безусловного этапа и у сработавшего
   *  «иначе» условие одинаково пустое — различает их только это поле. */
  matched_by: 'always' | 'condition' | 'fallback';
  /** Снимок «этапа подписи» на момент запуска. `requires_attachment` и
   *  `requires_comment` здесь — рабочие поля: правка маршрута не избавляет от
   *  документа (или пояснения) тех, кто ещё не решил. */
  approver_kind: ApproverKind;
  /** HR-должности, по которым этот снимок маршрута разрешил задачи. */
  role_ids: number[];
  requires_attachment: boolean;
  requires_comment: boolean;
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
  /** Факты объекта на момент запуска — по ним выбирались ветки. Ответ на
   *  «почему согласуют именно эти люди» через год после запуска. */
  subject_facts: Record<string, unknown>;
  subject_title: string | null;
  subject_url: string | null;
  /** Имя инициатора, развёрнутое бэкендом через apps.users. Может быть null,
   *  если инициатор неизвестен или пользователь удалён — тогда остаётся
   *  только `initiator_id`. */
  initiator_name: string | null;
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
  /** Решение потребует PDF и/или пояснения — видно уже в очереди, а не
   *  только в диалоге. */
  requires_attachment: boolean;
  requires_comment: boolean;
  file_id: string | null;
  initiator_id: number | null;
  created_at: string;
}

export interface SignoffEnums {
  quorum: EnumOption[];
  approver_kind: EnumOption[];
  process_state: EnumOption[];
  stage_state: EnumOption[];
  task_state: EnumOption[];
  /** Состояние предметного объекта — плашку с ним рисуют карточки чужих
   *  аппок (`SubmitForApproval`). */
  approval_state: EnumOption[];
}

// ─── Запросы ─────────────────────────────────────────────────────────────

export interface StageInput {
  order: number;
  name: string;
  quorum: Quorum;
  /** Минимум одна у `position` — этап без должностей движок не запустит. У
   *  `initiator` наоборот: список обязан быть пустым. */
  position_ids: number[];
  condition?: Condition;
  is_fallback?: boolean;
  approver_kind?: ApproverKind;
  requires_attachment?: boolean;
  requires_comment?: boolean;
}

/** PATCH этапа: `position_ids` заменяет список ЦЕЛИКОМ, а его отсутствие
 *  оставляет согласующих в покое. Не путать одно с другим.
 *
 *  То же и с `condition`: не прислать поле — «не трогать ветку», прислать
 *  пустой массив — «снять условие». */
export interface StageUpdateInput {
  order?: number;
  name?: string;
  quorum?: Quorum;
  position_ids?: number[];
  condition?: Condition;
  is_fallback?: boolean;
  /** Переключение на `initiator` стирает названных согласующих само —
   *  присылать вместе с ним пустой `approver_ids` не нужно (а непустой
   *  бэкенд отвергнет как противоречие). */
  approver_kind?: ApproverKind;
  requires_attachment?: boolean;
  requires_comment?: boolean;
}

export interface DecisionInput {
  /** `rework` — вернуть на доработку: круг закрывается, объект открывается
   *  для правки. Не то же, что `reject` (см. `ProcessState`). */
  decision: 'approve' | 'reject' | 'rework';
  comment?: string;
}

/** Возврат на доработку по УЖЕ ЗАКРЫТОМУ кругу (`POST /processes/:id/rework`).
 *  Пока согласование идёт, для этого есть решение `rework` по своему запросу. */
export interface ReworkInput {
  comment?: string;
}
