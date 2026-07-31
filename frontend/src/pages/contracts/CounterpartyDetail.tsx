/**
 * Страница карточки контрагента — рамка раздела «Договоры» вокруг общего
 * тела.
 *
 * Куда ведут ссылки signoff'а на `contracts.counterparty` — колбэк
 * `approval_hooks._describe_counterparty` строит именно этот путь.
 *
 * Само тело живёт в `components/contracts/CounterpartyDetailView`: то же
 * содержимое показывает карточка согласования, и рамка там другая.
 */

import { useParams } from 'react-router-dom';

import { ContractsShell } from '@/components/contracts/ContractsShell';
import CounterpartyDetailView from '@/components/contracts/CounterpartyDetailView';
import { BackLink } from '@/components/contracts/detail';

const CounterpartyDetail = () => {
  const { id } = useParams<{ id: string }>();

  return (
    <ContractsShell>
      <BackLink to="/contracts/counterparties">Ко всему реестру</BackLink>
      <CounterpartyDetailView id={Number(id)} />
    </ContractsShell>
  );
};

export default CounterpartyDetail;
