/**
 * orgEdit — pure helpers for manual org-chart editing (руководители/прямые
 * подчинённые). Kept free of React/@xyflow so it's testable in plain
 * vitest without mounting the canvas (jsdom can't give React Flow real
 * layout/pointer geometry — see OrgChart/index.tsx for why drag&drop uses
 * onConnect, not node dragging).
 */
import type { OrgEdge, OrgEdgeOrigin, OrgNode, OrgTree, RelationType } from '@/api/hr';
import i18next from '@/i18n';
import { translatedMap } from '@/lib/i18n/translatedMap';

/** Human labels for the "how was this decided" badge in the edit panel.
 *  Значения — ключи перевода: модуль импортируется раньше, чем загружен
 *  словарь, поэтому подпись берётся на чтение (см. `translatedMap`). */
export const ORIGIN_LABELS: Record<OrgEdgeOrigin, string> = translatedMap({
  employee: 'hr.orgChart.origin.employee',
  position: 'hr.orgChart.origin.position',
  department: 'hr.orgChart.origin.department',
  inferred: 'hr.orgChart.origin.inferred',
  structural: 'hr.orgChart.origin.structural',
  membership: 'hr.orgChart.origin.membership',
  employment: 'hr.orgChart.origin.employment',
});

/** origin-значения, для которых relation_id адресует реальную строку в БД —
 * то есть ровно там, где кнопка «Убрать»/переподчинение имеет смысл. */
const EDITABLE_ORIGINS: ReadonlySet<OrgEdgeOrigin> = new Set(['employee', 'position']);

export function isEditableEdge(edge: Pick<OrgEdge, 'origin' | 'relation_id'>): boolean {
  // relation_id > 0, а не просто != null: у ещё не подтверждённого сервером
  // ребра стоит OPTIMISTIC_RELATION_ID = -1, и действия над ним ушли бы на
  // бэкенд как DELETE .../relations/-1.
  return EDITABLE_ORIGINS.has(edge.origin)
    && edge.relation_id != null
    && edge.relation_id > 0;
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
  if (!sourceId || !targetId) return { ok: false, reason: i18next.t('hr.orgChart.connect.errors.bothNodes') };
  if (sourceId === targetId) return { ok: false, reason: i18next.t('hr.orgChart.connect.errors.self') };

  const sourceKind = nodeKind(sourceId);
  const targetKind = nodeKind(targetId);
  if (sourceKind === 'dept' || targetKind === 'dept') {
    return { ok: false, reason: i18next.t('hr.orgChart.connect.errors.departmentHead') };
  }
  if (sourceKind === null || targetKind === null) {
    return { ok: false, reason: i18next.t('hr.orgChart.connect.errors.unknownKind') };
  }
  if (sourceKind !== targetKind) {
    return { ok: false, reason: i18next.t('hr.orgChart.connect.errors.kindMismatch') };
  }
  if (!nodes.some((n) => n.id === sourceId) || !nodes.some((n) => n.id === targetId)) {
    return { ok: false, reason: i18next.t('hr.orgChart.connect.errors.notOnChart') };
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

/**
 * Оптимистичный редьюсер для пакетного добавления подчинённых к parentId.
 */
export function applyBatchSuperiorChange(
  tree: OrgTree,
  parentId: string,
  childIds: string[],
  relationType: string,
  origin: OrgEdgeOrigin,
): OrgTree {
  const childSet = new Set(childIds);
  const edges = tree.edges.filter((e) => !(
    childSet.has(e.target) && e.relation_type === relationType && isEditableEdge(e)
  ));
  for (const childId of childIds) {
    edges.push({
      source: parentId,
      target: childId,
      relation_type: relationType,
      relation_id: OPTIMISTIC_RELATION_ID,
      origin,
    });
  }
  return { ...tree, edges };
}

/**
 * Оптимистичный редьюсер: изменение типа связи существующего ребра.
 */
export function applyRelationTypeChange(
  tree: OrgTree,
  relationId: number,
  newRelationType: RelationType,
): OrgTree {
  return {
    ...tree,
    edges: tree.edges.map((e) =>
      e.relation_id === relationId
        ? { ...e, relation_type: newRelationType }
        : e
    ),
  };
}

/** Убрать ребро по relation_id (после успешного/оптимистичного DELETE). */
export function removeEdgeByRelationId(tree: OrgTree, relationId: number): OrgTree {
  return { ...tree, edges: tree.edges.filter((e) => e.relation_id !== relationId) };
}

/**
 * Оптимистично проставить руководителя отдела в meta dept-узла.
 * Полное имя тут взять неоткуда (в дереве лежат только id), поэтому имя
 * очищаем — его принесёт ближайший рефетч. Главное, что снятие руководителя
 * видно сразу, а не после round-trip.
 */
export function applyDepartmentManagerChange(
  tree: OrgTree,
  departmentId: number,
  employeeId: number | null,
): OrgTree {
  const nodeId = `dept_${departmentId}`;
  return {
    ...tree,
    nodes: tree.nodes.map((n) => (
      n.id === nodeId
        ? {
          ...n,
          meta: {
            ...(n.meta ?? {}),
            manager_id: employeeId,
            manager_name: null,
            manager_source: employeeId == null ? null : 'explicit',
          },
        }
        : n
    )),
  };
}

/**
 * Вычисляет цепочку руководителей снизу вверх до корня
 * Возвращает массив [rootNodeId, ..., parentNodeId, nodeId].
 */
export function resolveHierarchyChain(edges: OrgEdge[], nodeId: string, maxDepth = 15): string[] {
  const chain: string[] = [nodeId];
  const visited = new Set<string>([nodeId]);
  let curr = nodeId;

  while (chain.length < maxDepth) {
    const supEdge = resolveSuperiorEdge(edges, curr);
    if (!supEdge || !supEdge.source || visited.has(supEdge.source)) {
      break;
    }
    visited.add(supEdge.source);
    chain.unshift(supEdge.source);
    curr = supEdge.source;
  }

  return chain;
}

/**
 * Проверяет, является ли candidateId потомком targetId (чтобы избежать циклов).
 */
export function isNodeDescendant(edges: OrgEdge[], targetId: string, candidateId: string, maxDepth = 20): boolean {
  if (targetId === candidateId) return true;
  const queue = [targetId];
  const visited = new Set<string>([targetId]);
  let steps = 0;

  while (queue.length > 0 && steps < maxDepth * 10) {
    steps++;
    const curr = queue.shift()!;
    const reports = resolveDirectReports(edges, curr);
    for (const r of reports) {
      if (r.target === candidateId) return true;
      if (!visited.has(r.target)) {
        visited.add(r.target);
        queue.push(r.target);
      }
    }
  }

  return false;
}


/**
 * Ветка ответственности узла: он сам, ВСЕ его подчинённые вниз по дереву и
 * цепочка руководителей вверх до самого корня.
 *
 * Зачем и то и другое: «зона ответственности» читается только вместе с
 * контекстом — кому этот руководитель сам подчиняется. Поэтому вверх идём
 * до корня, а вниз забираем всё поддерево целиком.
 *
 * Граф может содержать кольца (данные грязные или связи разных типов
 * замыкают цикл), поэтому оба обхода идут с множеством посещённых — иначе
 * подсветка зациклилась бы и подвесила вкладку.
 */
export function collectBranch(
  edges: Pick<OrgEdge, 'source' | 'target'>[],
  nodeId: string,
): Set<string> {
  const childrenOf = new Map<string, string[]>();
  const parentsOf = new Map<string, string[]>();
  for (const e of edges) {
    const kids = childrenOf.get(e.source);
    if (kids) kids.push(e.target); else childrenOf.set(e.source, [e.target]);
    const dads = parentsOf.get(e.target);
    if (dads) dads.push(e.source); else parentsOf.set(e.target, [e.source]);
  }

  const branch = new Set<string>([nodeId]);

  const walk = (from: string, adjacency: Map<string, string[]>) => {
    const stack = [from];
    const seen = new Set<string>([from]);
    while (stack.length) {
      const current = stack.pop() as string;
      for (const next of adjacency.get(current) ?? []) {
        if (seen.has(next)) continue;
        seen.add(next);
        branch.add(next);
        stack.push(next);
      }
    }
  };

  walk(nodeId, childrenOf);  // вниз: все подчинённые
  walk(nodeId, parentsOf);   // вверх: цепочка руководителей до корня
  return branch;
}
