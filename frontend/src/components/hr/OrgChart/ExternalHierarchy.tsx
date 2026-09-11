import { Building2, CornerDownRight, Info } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { usePermissions } from '@/hooks/usePermissions';

/**
 * Внешняя иерархия — компании ниже по дереву владения (§1.4 спеки стадии 2).
 *
 * Только чтение: редактировать здесь нечего, дерево вычисляется из реестра
 * компаний. Данные приходят полем `subordinate_companies` ответа `/access/v1/me`.
 *
 * **Пустой список — нормальное состояние, а не сбой загрузки.** Внешняя
 * иерархия распространяется только на руководителей, и до тех пор пока в
 * кадровом учёте ни одна должность не помечена руководящей (это делает
 * переработка HR, §1.6), список пуст у всех. Экран обязан сказать это словами:
 * пустая область без объяснения читается как «не загрузилось», и разбираться
 * пойдут не туда.
 */

export function ExternalHierarchy() {
  const { t } = useTranslation();
  const { company, subordinateCompanies, isLoading } = usePermissions();

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        {t('common.loading', 'Загрузка…')}
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto rounded-xl border bg-card p-6">
      <div className="mb-4 flex items-start gap-2 rounded-lg border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
        <Info className="mt-0.5 h-4 w-4 shrink-0" />
        <p>
          {t(
            'access.hierarchy.externalHint',
            'Дерево выводится из иерархии компаний и не редактируется: сотрудник '
            + 'вышестоящей компании является начальником сотрудников нижестоящих. '
            + 'Правило распространяется на руководящие должности, у которых включено '
            + 'участие во внешней иерархии.',
          )}
        </p>
      </div>

      <div className="flex items-center gap-2 text-sm font-medium">
        <Building2 className="h-4 w-4 text-primary" />
        {company ?? t('access.hierarchy.noCompany', 'компания не определена')}
      </div>

      {subordinateCompanies.length > 0 ? (
        <ul className="mt-3 space-y-2 border-l pl-4">
          {subordinateCompanies.map((slug) => (
            <li key={slug} className="flex items-center gap-2 text-sm">
              <CornerDownRight className="h-4 w-4 text-muted-foreground" />
              <span className="font-mono">{slug}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-3 max-w-prose text-sm text-muted-foreground">
          {t(
            'access.hierarchy.externalEmpty',
            'Подчинённых компаний нет. Так и должно выглядеть, пока ни одна должность '
            + 'не помечена руководящей с участием во внешней иерархии — это не ошибка '
            + 'загрузки.',
          )}
        </p>
      )}
    </div>
  );
}

export default ExternalHierarchy;
