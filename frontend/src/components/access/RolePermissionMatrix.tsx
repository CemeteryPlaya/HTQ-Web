import { useTranslation } from 'react-i18next';

import { ACCESS_MODULES } from '@/lib/auth/modules';
import { LEVEL_ORDER, type AccessLevel } from '@/lib/auth/permissions';
import type { RolePermission } from '@/types/access';

/**
 * Матрица «модуль × уровень» — единственный редактор прав роли (§4.2).
 *
 * Набор всегда заменяется ЦЕЛИКОМ, поэтому компонент работает не со списком
 * изменений, а с полным состоянием: наружу уходит ровно то, что видно на
 * экране. Модуль с уровнем `none` в набор не попадает — отсутствие модуля и
 * есть «нет доступа», и хранить явный `none` значило бы завести второе
 * представление одного и того же.
 */

export interface RolePermissionMatrixProps {
  value: RolePermission[];
  onChange: (next: RolePermission[]) => void;
  disabled?: boolean;
}

const LEVEL_LABELS: Record<AccessLevel, { key: string; fallback: string }> = {
  none: { key: 'access.levels.none', fallback: 'Нет' },
  read: { key: 'access.levels.read', fallback: 'Чтение' },
  write: { key: 'access.levels.write', fallback: 'Запись' },
  admin: { key: 'access.levels.admin', fallback: 'Администрирование' },
};

export function RolePermissionMatrix({
  value,
  onChange,
  disabled = false,
}: RolePermissionMatrixProps) {
  const { t } = useTranslation();

  const current = new Map(value.map((item) => [item.module, item.level]));

  const setLevel = (module: string, level: AccessLevel) => {
    const next = ACCESS_MODULES
      .map(({ name }) => ({
        module: name,
        level: name === module ? level : (current.get(name) ?? 'none'),
      }))
      .filter((item): item is RolePermission => item.level !== 'none');
    onChange(next);
  };

  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full text-sm">
        <thead className="bg-muted/50 text-xs text-muted-foreground">
          <tr>
            <th scope="col" className="px-3 py-2 text-left font-medium">
              {t('access.catalog.moduleColumn', 'Модуль')}
            </th>
            {LEVEL_ORDER.map((level) => (
              <th key={level} scope="col" className="px-3 py-2 text-center font-medium">
                {t(LEVEL_LABELS[level].key, LEVEL_LABELS[level].fallback)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ACCESS_MODULES.map((module) => {
            const level = current.get(module.name) ?? 'none';
            return (
              <tr key={module.name} className="border-t">
                <th scope="row" className="px-3 py-2 text-left font-normal">
                  {t(module.titleKey, module.fallback)}
                  <span className="ml-2 text-xs text-muted-foreground">{module.name}</span>
                </th>
                {LEVEL_ORDER.map((candidate) => (
                  <td key={candidate} className="px-3 py-2 text-center">
                    <input
                      type="radio"
                      name={`level-${module.name}`}
                      value={candidate}
                      checked={level === candidate}
                      disabled={disabled}
                      onChange={() => setLevel(module.name, candidate)}
                      aria-label={`${t(module.titleKey, module.fallback)}: ${t(
                        LEVEL_LABELS[candidate].key,
                        LEVEL_LABELS[candidate].fallback,
                      )}`}
                      className="h-4 w-4 accent-primary"
                    />
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default RolePermissionMatrix;
