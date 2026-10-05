/**
 * Метка «Проверенный» (D-20): ставится порогом удачных документов или
 * вручную ФД. Ручное решение подписано отдельно — иначе непонятно, почему
 * у контрагента с пятью оплаченными счетами метки нет.
 */
import { useTranslation } from 'react-i18next';
import { ShieldAlert, ShieldCheck } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

interface Props {
  isVerified: boolean;
  override: boolean | null;
  className?: string;
}

export function VerifiedMark({ isVerified, override, className }: Props) {
  const { t } = useTranslation();
  const manual = override !== null && override !== undefined;
  return (
    <Badge
      variant="outline"
      className={cn(
        'gap-1 font-normal',
        isVerified
          ? 'border-emerald-300 text-emerald-800 dark:border-emerald-800 dark:text-emerald-300'
          : 'border-amber-300 text-amber-900 dark:border-amber-800 dark:text-amber-300',
        className,
      )}
      title={manual ? t('bpp.counterparties.verifiedManual', 'Решение финансового директора') : undefined}
    >
      {isVerified ? <ShieldCheck className="h-3.5 w-3.5" /> : <ShieldAlert className="h-3.5 w-3.5" />}
      {isVerified
        ? t('bpp.counterparties.verified', 'Проверенный')
        : t('bpp.counterparties.notVerified', 'Не проверен')}
      {manual && <span className="text-muted-foreground">({t('bpp.counterparties.byFd', 'ФД')})</span>}
    </Badge>
  );
}

export default VerifiedMark;
