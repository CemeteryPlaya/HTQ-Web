/**
 * Подмодуль «Бюджеты» (ТЗ §05 п.1, §06): реестр L-01 и форма F-01.
 *
 * Виден при `bpp:read` и признаке `view` на узле `bpp.budgets`: ФД, АДМ и
 * директора видят все строки, СН и ПМ — строки своей группы статей своих
 * проектов (фильтрует сервер). Создание и утверждение — узлы `bpp.budgets`
 * `create` и `bpp.budgets.approve` (ФД); кнопки даёт `allowed_actions`.
 */
import { lazy } from 'react';
import { Wallet } from 'lucide-react';

import type { BppGatedModule } from '../core/moduleAccess';

const BudgetCardPage = lazy(() => import('./BudgetCardPage'));

export const bppModule: BppGatedModule = {
  key: 'budgets',
  // ТЗ §05: «Бюджеты» — пункт 1 меню (порядок — номер пункта × 10).
  order: 10,
  menu: {
    labelKey: 'bpp.budgets.title',
    labelFallback: 'Бюджеты',
    path: 'budgets',
    icon: Wallet,
  },
  visible: (permissions) =>
    permissions.atLeast('bpp', 'read') && permissions.can('bpp.budgets', 'view'),
  routes: [
    { path: 'budgets', element: lazy(() => import('./BudgetsPage')) },
    { path: 'budgets/new', element: BudgetCardPage },
    { path: 'budgets/:id', element: BudgetCardPage },
  ],
};
