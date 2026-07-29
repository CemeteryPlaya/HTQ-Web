/**
 * Мелкие преобразования данных согласования — отдельно от компонентов,
 * чтобы не ломать fast refresh.
 */

import type { ProcessStage } from '@/types/signoff';

/** ISO → «12.03.2026, 14:05». Пустая строка, если даты нет. */
export function formatMoment(value: string | null): string {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/**
 * Этапы по группам `order`, группы — по возрастанию.
 *
 * Вся параллельность маршрута выражена этим числом: одинаковый `order` —
 * одновременно, разный — друг за другом. Группировка нужна везде, где ход
 * согласования показывается человеком, поэтому живёт здесь, а не в
 * компоненте.
 */
export function groupStages(stages: ProcessStage[]): ProcessStage[][] {
  const byOrder = new Map<number, ProcessStage[]>();
  for (const stage of stages) {
    const group = byOrder.get(stage.order);
    if (group) group.push(stage);
    else byOrder.set(stage.order, [stage]);
  }
  return [...byOrder.entries()]
    .sort(([a], [b]) => a - b)
    .map(([, group]) => group);
}
