import { Building2, Network } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';

/**
 * Выбор иерархии должностей — правило 4 спеки стадии 2 (§1.4).
 *
 * Иерархий две, и они разной природы:
 *
 * - **внутренняя** — дерево должностей внутри компании; его правят руками;
 * - **внешняя** — выводится из дерева владения компаниями и потому доступна
 *   ТОЛЬКО для чтения: руководитель вышестоящей компании является начальником
 *   сотрудников нижестоящих, и хранить это отдельно нельзя — два источника
 *   правды о подчинении разъедутся при первой же реорганизации.
 *
 * Переключатель именно переключатель, а не фильтр: показывать оба дерева
 * одновременно значило бы смешать редактируемое с вычисляемым.
 */

export type HierarchyKind = 'internal' | 'external';

export interface HierarchySwitchProps {
  value: HierarchyKind;
  onChange: (next: HierarchyKind) => void;
}

export function HierarchySwitch({ value, onChange }: HierarchySwitchProps) {
  const { t } = useTranslation();

  return (
    <div
      className="flex items-center gap-1 rounded-lg border bg-muted/30 p-0.5"
      role="group"
      aria-label={t('access.hierarchy.switchLabel', 'Иерархия должностей')}
    >
      <Button
        size="sm"
        variant={value === 'internal' ? 'default' : 'ghost'}
        className="h-7 gap-1.5 text-xs"
        aria-pressed={value === 'internal'}
        onClick={() => onChange('internal')}
      >
        <Building2 className="h-3.5 w-3.5" />
        {t('access.hierarchy.internal', 'Внутренняя')}
      </Button>
      <Button
        size="sm"
        variant={value === 'external' ? 'default' : 'ghost'}
        className="h-7 gap-1.5 text-xs"
        aria-pressed={value === 'external'}
        onClick={() => onChange('external')}
      >
        <Network className="h-3.5 w-3.5" />
        {t('access.hierarchy.external', 'Внешняя')}
      </Button>
    </div>
  );
}

export default HierarchySwitch;
