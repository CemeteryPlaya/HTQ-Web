/**
 * «Обзор» раздела «Тендеры» — заглушка каркаса (T0.4): документов модуля
 * ещё нет, и показать нечего. Сервер не опрашивается — ручки обзора нет.
 */
import { useTranslation } from 'react-i18next';
import { Gavel } from 'lucide-react';

export default function TenderOverviewPage() {
  const { t } = useTranslation();
  return (
    <div className="rounded-2xl border bg-card p-10 text-center">
      <Gavel className="mx-auto mb-3 h-8 w-8 text-muted-foreground" />
      <h2 className="text-lg font-semibold">
        {t('tender.overview.empty', 'Здесь появятся заявки и тендеры')}
      </h2>
      <p className="mt-1 text-sm text-muted-foreground">
        {t(
          'tender.overview.emptyHint',
          'Раздел готовится: заявки на тендер и сами тендеры подключатся следующими этапами.',
        )}
      </p>
    </div>
  );
}
