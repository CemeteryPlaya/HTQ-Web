/** Ссылка «К заявкам» — над карточкой и формой заявки на тендер. */
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';

import { TENDER_REQUESTS_BASE } from './api';

export function BackToRequests() {
  const { t } = useTranslation();
  return (
    <Link
      to={TENDER_REQUESTS_BASE}
      className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
    >
      <ArrowLeft className="h-4 w-4" />
      {t('tender.requests.back', 'К заявкам')}
    </Link>
  );
}
