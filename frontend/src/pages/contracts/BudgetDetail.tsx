/**
 * Страница карточки бюджета — рамка раздела «Договоры» вокруг общего тела.
 *
 * Куда ведут ссылки signoff'а на `contracts.budget` — колбэк
 * `approval_hooks._describe_budget` строит именно этот путь.
 *
 * Само тело живёт в `components/contracts/BudgetDetailView`: то же
 * содержимое показывает карточка согласования, и рамка там другая.
 */

import { useParams } from 'react-router-dom';

import { ContractsShell } from '@/components/contracts/ContractsShell';
import BudgetDetailView from '@/components/contracts/BudgetDetailView';
import { BackLink } from '@/components/contracts/detail';

const BudgetDetail = () => {
  const { id } = useParams<{ id: string }>();

  return (
    <ContractsShell>
      <BackLink to="/contracts/budgets">Ко всем бюджетам</BackLink>
      <BudgetDetailView id={Number(id)} />
    </ContractsShell>
  );
};

export default BudgetDetail;
