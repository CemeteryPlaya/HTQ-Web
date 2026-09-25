import { Archive } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { usePermissions } from '@/hooks/usePermissions';

/**
 * Полоса «компания в архиве — только чтение» (спека архива §7.2).
 *
 * Стоит в `Header` — он есть во всех раскладках, поэтому одна точка. Кнопки,
 * скрытые по `usePermissions`, исчезают сами (уровни в архиве не выше `read`);
 * те, что по уровню не прячутся, получат 403 `company_archived` и тост —
 * баннер предупреждает заранее.
 */
export function ArchivedCompanyBanner() {
  const { t } = useTranslation();
  const { companyArchived } = usePermissions();
  if (!companyArchived) return null;
  return (
    <div
      role="status"
      className="mt-3 border-t border-amber-300/70 bg-amber-50/90 text-amber-900 dark:border-amber-800/70 dark:bg-amber-950/40 dark:text-amber-200"
    >
      <div className="container-custom flex items-center gap-2 py-1.5 text-sm">
        <Archive className="h-4 w-4 shrink-0" />
        <span>{t('companies.archiveMode.banner', 'Компания в архиве — только чтение')}</span>
      </div>
    </div>
  );
}

export default ArchivedCompanyBanner;
