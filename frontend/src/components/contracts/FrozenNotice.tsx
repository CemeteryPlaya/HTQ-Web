/**
 * Раздел «Договоры» после переноса в «Закупки и оплаты» (A6.2, D-S6-4):
 * плашка «только чтение» и подпись «перенесён в ДГ-…» на карточках.
 *
 * Плашку рисует `ContractsShell` над любым экраном раздела; формы создания
 * и правки он вместо неё не показывает вовсе (`FrozenFormNotice`) — сервер
 * всё равно ответит 403 `contracts_frozen`.
 */
import { Archive, ArrowRight } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import type { MigratedTarget } from '@/types/contracts';

export function FrozenBanner() {
  const { t } = useTranslation();
  return (
    <Alert className="mb-6" data-testid="contracts-frozen-banner">
      <Archive className="h-4 w-4" />
      <AlertTitle>
        {t('contracts.frozen.title', 'Раздел перенесён в «Закупки и оплаты»')}
      </AlertTitle>
      <AlertDescription>
        {t(
          'contracts.frozen.text',
          'Это архив: документы доступны только для чтения. Новые договоры, счета и оплаты оформляются в разделе «Закупки и оплаты».',
        )}{' '}
        <Link to="/bpp" className="font-medium text-primary underline-offset-4 hover:underline">
          {t('contracts.frozen.goToBpp', 'Перейти в «Закупки и оплаты»')}
        </Link>
      </AlertDescription>
    </Alert>
  );
}

/** Вместо формы создания или правки в замороженном разделе. */
export function FrozenFormNotice() {
  const { t } = useTranslation();
  return (
    <div className="rounded-2xl border bg-card p-10 text-center text-sm text-muted-foreground">
      {t(
        'contracts.frozen.formClosed',
        'Раздел доступен только для чтения — создавать и править документы здесь больше нельзя.',
      )}
    </div>
  );
}

/** Карточка документа модуля, куда переехала запись. `null` — экрана нет. */
function migratedHref(target: MigratedTarget): string | null {
  const id = encodeURIComponent(target.target_id);
  switch (target.target_type) {
    case 'bpp.agreement': return `/bpp/agreements/${id}`;
    case 'bpp.invoice': return `/bpp/invoices/${id}`;
    case 'bpp.counterparty': return `/bpp/counterparties/${id}`;
    case 'bpp.purchase_request': return `/bpp/requests/${id}`;
    case 'bpp.accountable_funds_request': return `/bpp/accountable/${id}`;
    case 'bpp.budget': return `/bpp/budgets/${id}`;
    default: return null;
  }
}

/** «Перенесён в ДГ-…» — ссылкой на документ модуля. Пусто — ничего. */
export function MigratedTo({ targets }: { targets?: MigratedTarget[] }) {
  const { t } = useTranslation();
  if (!targets || targets.length === 0) return null;
  return (
    <div className="mb-4 flex flex-wrap items-center gap-2 rounded-lg border border-primary/30 bg-primary/5 px-3 py-2 text-sm">
      <ArrowRight className="h-4 w-4 text-primary" />
      <span>{t('contracts.frozen.migratedTo', 'Перенесён в')}</span>
      {targets.map((target) => {
        const label = target.number
          ?? t('contracts.frozen.migratedCard', 'карточку в «Закупках и оплатах»');
        const href = migratedHref(target);
        return href ? (
          <Link key={`${target.target_type}:${target.target_id}`} to={href}
            className="font-medium text-primary underline-offset-4 hover:underline">
            {label}
          </Link>
        ) : (
          <span key={`${target.target_type}:${target.target_id}`} className="font-medium">{label}</span>
        );
      })}
    </div>
  );
}
