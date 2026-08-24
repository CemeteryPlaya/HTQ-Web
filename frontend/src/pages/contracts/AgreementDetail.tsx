/**
 * Страница карточки договора — рамка раздела «Договоры» вокруг общего тела.
 *
 * Куда ведут ссылки signoff'а на `contracts.agreement` — колбэк
 * `approval_hooks._describe_agreement` строит именно этот путь.
 *
 * Само тело живёт в `components/contracts/AgreementDetailView` (там же
 * описаны смена статуса и работа со сканом): то же содержимое показывает
 * карточка согласования, и рамка там другая.
 */

import { useParams } from 'react-router-dom';

import { ContractsShell } from '@/components/contracts/ContractsShell';
import AgreementDetailView from '@/components/contracts/AgreementDetailView';
import { BackLink } from '@/components/contracts/detail';
import { useTranslation } from 'react-i18next';

const AgreementDetail = () => {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();

  return (
    <ContractsShell>
      <BackLink to="/contracts/agreements">{t('contracts.agreement.backToList')}</BackLink>
      <AgreementDetailView id={Number(id)} />
    </ContractsShell>
  );
};

export default AgreementDetail;
