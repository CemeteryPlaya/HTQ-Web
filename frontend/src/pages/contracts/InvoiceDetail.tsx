/**
 * Страница карточки счёта на оплату — рамка раздела «Договоры» вокруг тела.
 *
 * Тело вынесено в `components/contracts/InvoiceDetailView` по образцу
 * договора: когда согласование счёта подключат, то же тело сможет показать
 * карточка согласования в своей рамке.
 */

import { useParams } from 'react-router-dom';

import { ContractsShell } from '@/components/contracts/ContractsShell';
import InvoiceDetailView from '@/components/contracts/InvoiceDetailView';
import { BackLink } from '@/components/contracts/detail';

const InvoiceDetail = () => {
  const { id } = useParams<{ id: string }>();

  return (
    <ContractsShell>
      <BackLink to="/contracts/invoices">Ко всем счетам</BackLink>
      <InvoiceDetailView id={Number(id)} />
    </ContractsShell>
  );
};

export default InvoiceDetail;
