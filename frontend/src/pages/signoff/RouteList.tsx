/** `/signoff/routes` — маршруты согласования всех типов (администратор).
 *
 * Сам список живёт в `components/signoff/RouteListPanel`: он же встроен в
 * раздел «Закупки и оплаты» для документов модуля (В-09). Здесь остаётся
 * только рамка раздела и заголовок.
 */

import { GitBranch } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { RouteListPanel } from '@/components/signoff/RouteListPanel';
import { SignoffShell } from '@/components/signoff/SignoffShell';

const RouteList = () => {
  const { t } = useTranslation();
  return (
    <SignoffShell>
      <div className="mb-6 flex items-center gap-3">
        <GitBranch className="h-7 w-7 text-muted-foreground" />
        <div>
          <h1 className="text-3xl font-bold">{t('signoff.nav.routes')}</h1>
          <p className="text-sm text-muted-foreground">
            {t('signoff.routes.subtitle')}
          </p>
        </div>
      </div>
      <RouteListPanel />
    </SignoffShell>
  );
};

export default RouteList;
