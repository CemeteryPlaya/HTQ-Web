/**
 * Мелкие преобразования данных согласования — отдельно от компонентов,
 * чтобы не ломать fast refresh.
 */

import type { Condition, ConditionOp, ProcessStage, SubjectField } from '@/types/signoff';

/** Подписи операторов условия — те же слова, что в текстах ошибок бэкенда. */
export const OP_LABELS: Record<ConditionOp, string> = {
  eq: 'равно',
  in: 'одно из',
  not_in: 'не из',
  gt: 'больше',
  gte: 'больше или равно',
  lt: 'меньше',
  lte: 'меньше или равно',
};

/**
 * Условие ветки одной строкой — для карточек, где места на редактор нет.
 *
 * Значения справочника разворачиваются в подписи: `admin_country_id одно из
 * [1, 2]` читателю ничего не говорит, «Страна одно из Казахстан, Узбекистан»
 * — говорит. Без `fields` (их неоткуда взять, например в списке процессов)
 * останутся сырые ключи: хуже, но всё же читаемо.
 */
export function conditionText(condition: Condition, fields: SubjectField[]): string {
  return condition
    .map((predicate) => {
      const field = fields.find((item) => item.key === predicate.field);
      const label = field?.label || predicate.field;

      const render = (raw: unknown) => {
        const option = field?.options.find((item) => item.value === raw);
        return option ? option.label : String(raw);
      };

      const value = Array.isArray(predicate.value)
        ? predicate.value.map(render).join(', ')
        : render(predicate.value);

      return `${label} ${OP_LABELS[predicate.op]} ${value}`;
    })
    .join(' и ');
}

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
