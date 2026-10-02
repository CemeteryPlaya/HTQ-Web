/**
 * «Маршруты согласования» раздела «Закупки и оплаты» — общий список
 * `RouteListPanel`, суженный до документов модуля (`bpp.*`); карточка
 * маршрута открывается внутри раздела.
 */
import { useTranslation } from 'react-i18next';

import { RouteListPanel } from '@/components/signoff/RouteListPanel';

const isBppSubjectType = (subjectType: string): boolean =>
  subjectType.startsWith('bpp.');

const bppRouteHref = (routeId: number): string => `/bpp/routes/${routeId}`;

export default function RoutesPage() {
  const { t } = useTranslation();
  return (
    <section className="space-y-4">
      <div>
        <h2 className="text-2xl font-bold">{t('bpp.routes.title', 'Маршруты согласования')}</h2>
        <p className="text-sm text-muted-foreground">
          {t('bpp.routes.subtitle',
            'Кто и в каком порядке согласует документы модуля. Правят финансовый директор и администратор модуля.')}
        </p>
      </div>
      <RouteListPanel subjectFilter={isBppSubjectType} routeHref={bppRouteHref} />
    </section>
  );
}
