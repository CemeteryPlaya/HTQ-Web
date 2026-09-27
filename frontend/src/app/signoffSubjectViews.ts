/**
 * Чем показать предметный объект внутри карточки согласования.
 *
 * `apps.signoff` согласует строку в ЧУЖОЙ таблице и знает о ней ровно две
 * вещи — `subject_type` и `subject_id`. Заголовок и ссылку ему отдаёт сама
 * предметная аппка (колбэк `describe` в её `approval_hooks`), но нарисовать
 * документ по ним нельзя: нужен компонент, а компонент — это уже код
 * предметного раздела.
 *
 * Отсюда эта карта. Она лежит в `app/` — слое сборки приложения, который по
 * определению знает обо всех разделах, — а не в `components/signoff/`.
 * Причина та же, по которой на бэкенде зависимость строго односторонняя
 * (contracts импортирует `signoff.interface`, обратно — никогда, см.
 * `apps/contracts/approval_hooks.py`): раздел согласований не должен знать
 * про договоры, иначе завтра он будет знать про кадры, заявки и почту.
 *
 * `lazy()` — чтобы чанк раздела «Договоры» не грузился в разделе
 * согласований, пока не открыт процесс соответствующего типа.
 *
 * Ключи — те же строки, что регистрирует бэкенд (`SIGNOFF_SUBJECT_TYPE` на
 * модели). Типа нет в карте — карточка процесса просто не покажет документ:
 * заголовок и ссылка на объект в ней остаются в любом случае.
 *
 * Ключ объекта signoff отдаёт строкой (`ApprovalProcess.subject_id`): у
 * документов БЗО это UUID, у старых доменов — целое число в строке. Поэтому
 * контракт карты — строковый `id`, а представления старых доменов, которые
 * держат `id: number`, подключаются через `intKeyed`: переводить ключ в
 * число — забота этого слоя, а не каждого компонента. Прямой
 * `Number(subject_id)` на странице процесса дал бы UUID-документу `NaN`.
 */

import {
  createElement,
  lazy,
  type ComponentType,
  type LazyExoticComponent,
} from 'react';

/** Контракт предметного представления: ключ объекта и признак вставки. */
export interface SubjectViewProps {
  id: string;
  embedded?: boolean;
}

/** Представление домена с целыми ключами (договоры, заявки конструктора). */
export interface IntSubjectViewProps {
  id: number;
  embedded?: boolean;
}

export type SubjectView = LazyExoticComponent<ComponentType<SubjectViewProps>>;

type Loader<P> = () => Promise<{ default: ComponentType<P> }>;

/** Представление, которое принимает ключ как есть — строкой (UUID). */
export const stringKeyed = (load: Loader<SubjectViewProps>): SubjectView =>
  lazy(load);

/** Представление с целым ключом: строка процесса переводится в число. */
export const intKeyed = (load: Loader<IntSubjectViewProps>): SubjectView =>
  lazy(async () => {
    const { default: View } = await load();
    const IntKeyed = ({ id, embedded }: SubjectViewProps) =>
      createElement(View, { id: Number(id), embedded });
    return { default: IntKeyed };
  });

export const SIGNOFF_SUBJECT_VIEWS: Record<string, SubjectView> = {
  // Модуль БЗО — документы с UUID-ключом.
  'bpp.purchase_request': stringKeyed(
    () => import('@/features/bpp/requests/RequestSignoffView'),
  ),
  // Заявка конструктора «Запросы»: тот же движок согласует и её.
  'approvals.request': intKeyed(
    () => import('@/features/requests/components/RequestSubjectView'),
  ),
  'contracts.budget': intKeyed(() => import('@/components/contracts/BudgetDetailView')),
  'contracts.counterparty': intKeyed(
    () => import('@/components/contracts/CounterpartyDetailView'),
  ),
  'contracts.agreement': intKeyed(
    () => import('@/components/contracts/AgreementDetailView'),
  ),
  'contracts.invoice': intKeyed(() => import('@/components/contracts/InvoiceDetailView')),
  'contracts.advance_payment': intKeyed(
    () => import('@/components/contracts/AdvancePaymentDetailView'),
  ),
  'contracts.accountable_funds_request': intKeyed(
    () => import('@/components/contracts/AccountableFundsRequestDetailView'),
  ),
  'contracts.advance_report': intKeyed(
    () => import('@/components/contracts/AdvanceReportDetailView'),
  ),
  'contracts.contract_payment': intKeyed(
    () => import('@/components/contracts/ContractPaymentDetailView'),
  ),
  'contracts.completion_act': intKeyed(
    () => import('@/components/contracts/CompletionActDetailView'),
  ),
  'contracts.goods_invoice': intKeyed(
    () => import('@/components/contracts/GoodsInvoiceDetailView'),
  ),
};
