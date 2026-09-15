import { useQuery } from '@tanstack/react-query';
import { Building2, CornerDownRight, Info } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { companiesApi } from '@/api/companies';
import { Badge } from '@/components/ui/badge';
import { usePermissions } from '@/hooks/usePermissions';
import type { CompanyTreeNode } from '@/types/companies';

/**
 * Внешняя иерархия — дерево владения компаниями (§1.4 спеки стадии 2).
 *
 * Только чтение: редактировать здесь нечего, дерево вычисляется из реестра
 * компаний, а участие должности в нём задаётся в её карточке.
 *
 * **Пустой список — нормальное состояние, а не сбой загрузки**, и экран обязан
 * различать два разных «пусто»: под компанией вообще нет нижестоящих, и
 * нижестоящие есть, но должность смотрящего не помечена руководящей. Пустая
 * область без объяснения читается как «не загрузилось», и разбираться пойдут
 * не туда.
 *
 * **Деградация вместо ошибки.** Реестр компаний закрыт правом `companies:read`,
 * которого у кадровика может не быть. Тогда показываем то, что доступно
 * каждому вошедшему, — список слагов из `/access/v1/me`, — и подписываем, что
 * полное дерево требует доступа к реестру. Это не подмена значения
 * (`htqweb/fallback.py` тут ни при чём), а разный объём данных для разных прав.
 *
 * **Наследованные права тоже объясняются здесь** (задача 6 блока C): экран уже
 * про дерево владения, а наследование — это и есть эффект того дерева на
 * зрителя. Имена компаний резолвятся по уже загруженному дереву; когда реестр
 * закрыт, деградируем до тех же слагов, что и подчинённые компании выше.
 */

function nameBySlug(tree: CompanyTreeNode[]): Map<string, string> {
  const map = new Map<string, string>();
  const walk = (nodes: CompanyTreeNode[]) => {
    for (const node of nodes) {
      map.set(node.slug, node.name);
      if (node.children.length > 0) walk(node.children);
    }
  };
  walk(tree);
  return map;
}

function TreeBranch({ node, depth, current, subordinate }: {
  node: CompanyTreeNode; depth: number; current: string | null; subordinate: Set<string>;
}) {
  const { t } = useTranslation();
  const isCurrent = node.slug === current;
  const isSubordinate = subordinate.has(node.slug);

  return (
    <li>
      <div
        className={`flex items-center gap-2 rounded-md px-2 py-1.5 text-sm ${isCurrent ? 'bg-accent font-medium' : ''}`}
        style={{ paddingLeft: `${0.5 + depth * 1.25}rem` }}
      >
        {depth > 0
          ? <CornerDownRight className="h-4 w-4 shrink-0 text-muted-foreground" />
          : <Building2 className="h-4 w-4 shrink-0 text-primary" />}
        <span>{node.name}</span>
        {isCurrent && (
          <Badge variant="outline">{t('access.hierarchy.youAreHere', 'ваша компания')}</Badge>
        )}
        {isSubordinate && (
          <Badge variant="secondary">{t('access.hierarchy.subordinate', 'подчинённая')}</Badge>
        )}
      </div>
      {node.children.length > 0 && (
        <ul>
          {node.children.map((child) => (
            <TreeBranch key={child.slug} node={child} depth={depth + 1}
              current={current} subordinate={subordinate} />
          ))}
        </ul>
      )}
    </li>
  );
}

export function ExternalHierarchy() {
  const { t } = useTranslation();
  const { company, subordinateCompanies, inheritedFrom = [], isLoading } = usePermissions();
  const treeQuery = useQuery({
    queryKey: ['companies', 'tree'],
    queryFn: async () => (await companiesApi.tree()).data,
    retry: false,
    staleTime: 5 * 60 * 1000,
  });

  const subordinate = new Set(subordinateCompanies);
  // Доступность реестра — вопрос успеха запроса, а не количества узлов в
  // ответе: пустое, но успешное дерево — это не «доступа нет», это «нижестоящих
  // компаний нет», и это отдельное объяснение ниже (`externalEmpty`).
  const registryAvailable = treeQuery.isSuccess;
  // Имена предков резолвятся по уже загруженному дереву; без доступа к реестру
  // (та же деградация, что и у подчинённых компаний ниже) остаются слагами.
  const names = registryAvailable ? nameBySlug(treeQuery.data ?? []) : null;
  const inheritedNames = inheritedFrom.map((slug) => names?.get(slug) ?? slug);

  // `usePermissions()` кэшируется на 5 минут и часто уже тёплый, пока дерево
  // компаний ещё в полёте (`useQuery` стартует в `pending`, `isSuccess` в этот
  // момент ложно). Показывать деградацию в эту секунду означало бы на миг
  // сказать полноправному пользователю, что реестр ему закрыт, — поэтому ждём
  // оба источника, а не только `isLoading`.
  if (isLoading || treeQuery.isPending) {
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
            + 'Связь означает подчинение, а не передачу прав. Правило действует для '
            + 'руководящих должностей, у которых включено участие во внешней иерархии.',
          )}
        </p>
      </div>

      {registryAvailable ? (
        <ul className="space-y-0.5">
          {(treeQuery.data ?? []).map((node) => (
            <TreeBranch key={node.slug} node={node} depth={0}
              current={company} subordinate={subordinate} />
          ))}
        </ul>
      ) : (
        <div>
          <div className="flex items-center gap-2 text-sm font-medium">
            <Building2 className="h-4 w-4 text-primary" />
            {company ?? t('access.hierarchy.noCompany', 'компания не определена')}
          </div>
          {subordinateCompanies.length > 0 && (
            <ul className="mt-3 space-y-2 border-l pl-4">
              {subordinateCompanies.map((slug) => (
                <li key={slug} className="flex items-center gap-2 text-sm">
                  <CornerDownRight className="h-4 w-4 text-muted-foreground" />
                  <span className="font-mono">{slug}</span>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-3 max-w-prose text-xs text-muted-foreground">
            {t(
              'access.hierarchy.registryClosed',
              'Полное дерево компаний показывается при доступе к реестру компаний; '
              + 'здесь перечислено то, что видно по вашим правам.',
            )}
          </p>
        </div>
      )}

      {inheritedFrom.length > 0 && (
        <p className="mt-4 max-w-prose text-sm text-muted-foreground">
          {t('access.hierarchy.inheritedFrom',
             'Ваши права в этой компании действуют также от должности в:')}{' '}
          <span className="font-medium text-foreground">{inheritedNames.join(', ')}</span>
        </p>
      )}

      {subordinateCompanies.length === 0 && (
        <p className="mt-4 max-w-prose text-sm text-muted-foreground">
          {t(
            'access.hierarchy.externalEmpty',
            'Подчинённых компаний нет: ваша должность не помечена руководящей с '
            + 'участием во внешней иерархии. Это не ошибка загрузки — отметка ставится '
            + 'в карточке должности.',
          )}
        </p>
      )}
    </div>
  );
}

export default ExternalHierarchy;
