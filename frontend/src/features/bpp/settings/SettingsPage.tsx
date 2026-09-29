/**
 * «Настройки» раздела «Закупки и оплаты» (ТЗ §05 п.10 «Администрирование»,
 * §18; A3.1): счета организации и шаблоны выписок. Открытая вкладка — в
 * `?tab=`, чтобы ссылка из формы загрузки выписки («счетов нет — заведите»)
 * вела прямо на нужную.
 *
 * Правка — по узлу `bpp.settings` `edit` (АДМ), просмотр — `bpp.settings`
 * или `bpp.bank` `view`; кнопки прячутся без права, судья — сервер (403).
 *
 * Вкладки «Параметры модуля» (порог метки «Проверенный» у контрагента,
 * `ModuleSetting`) нет: у сервера пока нет ручки чтения и записи настроек
 * модуля — вкладка появится вместе с ней.
 */
import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router-dom';

import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { usePermissions } from '@/hooks/usePermissions';

import { AccountsTab } from './AccountsTab';
import { TemplatesTab } from './TemplatesTab';

const TABS = ['accounts', 'templates'] as const;
type TabKey = (typeof TABS)[number];

const isTab = (value: string | null): value is TabKey =>
  TABS.some((tab) => tab === value);

export function SettingsPage() {
  const { t } = useTranslation();
  const permissions = usePermissions();
  const canEdit = permissions.can('bpp.settings', 'edit');
  const [params, setParams] = useSearchParams();
  const requested = params.get('tab');
  const current: TabKey = isTab(requested) ? requested : 'accounts';

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
        <h2 className="text-xl font-semibold">{t('bpp.bankSettings.title', 'Настройки')}</h2>
        <p className="text-sm text-muted-foreground">
          {t('bpp.bankSettings.subtitle', 'Банковские счета организации и шаблоны разбора выписок для «Оплаты факт». Запись не удаляется, а уходит в архив.')}
        </p>
      </div>
      <Tabs value={current} onValueChange={select}>
        <TabsList className="h-auto flex-wrap justify-start">
          <TabsTrigger value="accounts">{t('bpp.bankSettings.tabs.accounts', 'Счета организации')}</TabsTrigger>
          <TabsTrigger value="templates">{t('bpp.bankSettings.tabs.templates', 'Шаблоны выписок')}</TabsTrigger>
        </TabsList>
        <TabsContent value="accounts" className="pt-4">
          {current === 'accounts' && <AccountsTab canEdit={canEdit} />}
        </TabsContent>
        <TabsContent value="templates" className="pt-4">
          {current === 'templates' && <TemplatesTab canEdit={canEdit} />}
        </TabsContent>
      </Tabs>
    </div>
  );
}

export default SettingsPage;
