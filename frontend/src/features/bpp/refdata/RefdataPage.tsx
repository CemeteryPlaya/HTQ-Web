/**
 * «Справочники» раздела «Закупки и оплаты» (ТЗ §18, задача 9, A2.4):
 * страны, валюты и курсы, единицы измерения, статьи бюджета, НДС и МРП.
 *
 * Справочники общие на группу (схема `public`, D-03): читают все, у кого
 * есть `refdata:read`, правит только управляющая компания — кнопки правки
 * включает `can_edit` из ответа сервера (`ArchivableTable`,
 * `PeriodicSection`). Открытая вкладка — в `?tab=`, чтобы ссылка вела
 * прямо в нужный справочник.
 */
import { lazy, Suspense } from 'react';
import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router-dom';

import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

// Вкладки грузятся по требованию: курсы НБРК — тысячи строк, и читать их,
// пока человек смотрит единицы измерения, незачем.
const TABS = [
  { key: 'articles', labelKey: 'bpp.refdata.tabs.articles', label: 'Статьи бюджета',
    Screen: lazy(() => import('./ArticlesTab')) },
  { key: 'currencies', labelKey: 'bpp.refdata.tabs.currencies', label: 'Валюты и курсы',
    Screen: lazy(() => import('./CurrenciesTab')) },
  { key: 'vat-mrp', labelKey: 'bpp.refdata.tabs.vatMrp', label: 'НДС и МРП',
    Screen: lazy(() => import('./VatMrpTab')) },
  { key: 'uoms', labelKey: 'bpp.refdata.tabs.uoms', label: 'Единицы измерения',
    Screen: lazy(() => import('./UomsTab')) },
  { key: 'countries', labelKey: 'bpp.refdata.tabs.countries', label: 'Страны',
    Screen: lazy(() => import('./CountriesTab')) },
] as const;

type TabKey = (typeof TABS)[number]['key'];

const isTab = (value: string | null): value is TabKey =>
  TABS.some((tab) => tab.key === value);

export default function RefdataPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const requested = params.get('tab');
  const current: TabKey = isTab(requested) ? requested : TABS[0].key;

  const select = (value: string) => {
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      next.set('tab', value);
      return next;
    }, { replace: true });
  };

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-semibold">{t('bpp.refdata.title', 'Справочники')}</h2>
        <p className="text-sm text-muted-foreground">
          {t(
            'bpp.refdata.subtitle',
            'Общие для всех компаний группы. Запись не удаляется, а уходит в архив: в новых документах её не выбрать, в старых она остаётся.',
          )}
        </p>
      </div>
      <Tabs value={current} onValueChange={select}>
        <TabsList className="h-auto flex-wrap justify-start">
          {TABS.map((tab) => (
            <TabsTrigger key={tab.key} value={tab.key}>{t(tab.labelKey, tab.label)}</TabsTrigger>
          ))}
        </TabsList>
        {TABS.map(({ key, Screen }) => (
          <TabsContent key={key} value={key} className="pt-4">
            {current === key && (
              <Suspense fallback={<Skeleton className="h-64 w-full" />}>
                <Screen />
              </Suspense>
            )}
          </TabsContent>
        ))}
      </Tabs>
    </div>
  );
}
