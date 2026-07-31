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
 */

import { lazy, type ComponentType, type LazyExoticComponent } from 'react';

/** Контракт предметного представления: id строки и признак вставки. */
export interface SubjectViewProps {
  id: number;
  embedded?: boolean;
}

export type SubjectView = LazyExoticComponent<ComponentType<SubjectViewProps>>;

export const SIGNOFF_SUBJECT_VIEWS: Record<string, SubjectView> = {
  'contracts.budget': lazy(() => import('@/components/contracts/BudgetDetailView')),
  'contracts.counterparty': lazy(
    () => import('@/components/contracts/CounterpartyDetailView'),
  ),
  'contracts.agreement': lazy(
    () => import('@/components/contracts/AgreementDetailView'),
  ),
};
