/**
 * orgEdit — pure helpers for manual org-chart editing (руководители/прямые
 * подчинённые). Kept free of React/@xyflow so it's testable in plain
 * vitest without mounting the canvas (jsdom can't give React Flow real
 * layout/pointer geometry — see OrgChart/index.tsx for why drag&drop uses
 * onConnect, not node dragging).
 */
import type { OrgEdge, OrgEdgeOrigin, OrgNode, OrgTree } from '@/api/hr';

/** Human labels for the "how was this decided" badge in the edit panel. */
export const ORIGIN_LABELS: Record<OrgEdgeOrigin, string> = {
  employee: 'задано вручную',
  position: 'из связи должностей',
  department: 'руководитель отдела',
  inferred: 'определено автоматически',
  structural: 'структура отделов',
  membership: 'состоит в отделе',
  employment: 'состоит в отделе',
};

/** origin-значения, для которых relation_id адресует реальную строку в БД —
 * то есть ровно там, где кнопка «Убрать»/переподчинение имеет смысл. */
const EDITABLE_ORIGINS: ReadonlySet<OrgEdgeOrigin> = new Set(['employee', 'position']);

export function isEditableEdge(edge: Pick<OrgEdge, 'origin' | 'relation_id'>): boolean {
  return EDITABLE_ORIGINS.has(edge.origin) && edge.relation_id != null;
}

/**
 * Руководитель узла — ребро, где узел является target. Предпочитаем
 * relation_type="direct" (как и сам бэкенд: ReportingRelation/
 * EmployeeReportingOverride резолвят "direct" первым), иначе первое попавшееся.
 */
export function resolveSuperiorEdge(edges: OrgEdge[], nodeId: string): OrgEdge | null {
  const incoming = edges.filter((e) => e.target === nodeId);
  if (incoming.length === 0) return null;
  return incoming.find((e) => e.relation_type === 'direct') ?? incoming[0];
}

/** Прямые подчинённые узла — все рёбра, где узел является source. */
export function resolveDirectReports(edges: OrgEdge[], nodeId: string): OrgEdge[] {
  return edges.filter((e) => e.source === nodeId);
}

function nodeKind(id: string): 'dept' | 'pos' | 'emp' | null {
  if (id.startsWith('dept_')) return 'dept';
  if (id.startsWith('pos_')) return 'pos';
  if (id.startsWith('emp_')) return 'emp';
  return null;
}

export type ConnectionCheck = { ok: true } | { ok: false; reason: string };

/**
 * Может ли пользователь протянуть связь source -> target на схеме
 * (source = будущий руководитель, target = будущий подчинённый).
 * Отделы (dept_*) сюда не участвуют — руководитель отдела правится через
 * отдельный контрол в панели (setDepartmentManager), не перетаскиванием.
 */
export function isValidOrgConnection(
  nodes: OrgNode[], sourceId: string | null, targetId: string | null,
): ConnectionCheck {
  if (!sourceId || !targetId) return { ok: false, reason: 'Не выбраны оба узла' };
  if (sourceId === targetId) return { ok: false, reason: 'Нельзя подчинить узел самому себе' };

  const sourceKind = nodeKind(sourceId);
  const targetKind = nodeKind(targetId);
  if (sourceKind === 'dept' || targetKind === 'dept') {
    return { ok: false, reason: 'Руководитель отдела назначается отдельно, не перетаскиванием' };
  }
  if (sourceKind === null || targetKind === null) {
    return { ok: false, reason: 'Неизвестный тип узла' };
  }
  if (sourceKind !== targetKind) {
    return { ok: false, reason: 'Можно соединять только должность с должностью или сотрудника с сотрудником' };
  }
  if (!nodes.some((n) => n.id === sourceId) || !nodes.some((n) => n.id === targetId)) {
    return { ok: false, reason: 'Узел не найден на текущей схеме' };
  }
  return { ok: true };
}

/** Числовой id из строкового id узла ("pos_42" -> 42), либо null. */
export function numericIdFromNodeId(nodeId: string): number | null {
  const parts = nodeId.split('_');
  const raw = parts[parts.length - 1];
  const n = raw ? Number(raw) : NaN;
  return Number.isFinite(n) ? n : null;
}

/** Sentinel relation_id для рёбер, ещё не подтверждённых сервером —
 * действия над ними (повторное удаление/переподчинение) блокируются в UI,
 * пока мутация не осядет. */
export const OPTIMISTIC_RELATION_ID = -1;

/**
 * Оптимистичный редьюсер дерева: подчинить childId узлу parentId с данным
 * relation_type. Убирает прежнее ребро той же природы (editable, тот же
 * relation_type) на childId, если было, и добавляет новое — ровно то, что
 * произойдёт на сервере при DELETE старой связи + POST новой.
 */
export function applySuperiorChange(
  tree: OrgTree,
  parentId: string,
  childId: string,
  relationType: string,
  origin: OrgEdgeOrigin,
): OrgTree {
  const edges = tree.edges.filter((e) => !(
    e.target === childId && e.relation_type === relationType && isEditableEdge(e)
  ));
  edges.push({
    source: parentId,
    target: childId,
    relation_type: relationType,
    relation_id: OPTIMISTIC_RELATION_ID,
    origin,
  });
  return { ...tree, edges };
}

/** Убрать ребро по relation_id (после успешного/оптимистичного DELETE). */
export function removeEdgeByRelationId(tree: OrgTree, relationId: number): OrgTree {
  return { ...tree, edges: tree.edges.filter((e) => e.relation_id !== relationId) };
}
