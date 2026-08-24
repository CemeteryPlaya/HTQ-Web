import { describe, expect, it } from 'vitest';

import type { OrgEdge, OrgNode, OrgTree } from '@/api/hr';
import {
  applyBatchSuperiorChange,
  applyDepartmentManagerChange,
  collectBranch,
  applyRelationTypeChange,
  applySuperiorChange,
  isEditableEdge,
  isNodeDescendant,
  isValidOrgConnection,
  numericIdFromNodeId,
  OPTIMISTIC_RELATION_ID,
  removeEdgeByRelationId,
  resolveDirectReports,
  resolveHierarchyChain,
  resolveSuperiorEdge,
} from '../orgEdit';

function edge(partial: Partial<OrgEdge> & Pick<OrgEdge, 'source' | 'target'>): OrgEdge {
  return {
    relation_type: 'direct',
    relation_id: null,
    origin: 'inferred',
    ...partial,
  };
}

function node(id: string): OrgNode {
  return { id, label: id, type: id.startsWith('dept_') ? 'department' : id.startsWith('pos_') ? 'position' : 'employee' };
}

describe('resolveSuperiorEdge', () => {
  it('returns null when there is no incoming edge', () => {
    expect(resolveSuperiorEdge([], 'pos_1')).toBeNull();
  });

  it('prefers the direct-type edge over other types', () => {
    const edges = [
      edge({ source: 'pos_2', target: 'pos_1', relation_type: 'functional' }),
      edge({ source: 'pos_3', target: 'pos_1', relation_type: 'direct' }),
    ];
    expect(resolveSuperiorEdge(edges, 'pos_1')?.source).toBe('pos_3');
  });

  it('falls back to the first incoming edge when none is direct', () => {
    const edges = [edge({ source: 'pos_2', target: 'pos_1', relation_type: 'project' })];
    expect(resolveSuperiorEdge(edges, 'pos_1')?.source).toBe('pos_2');
  });
});

describe('resolveDirectReports', () => {
  it('returns all outgoing edges from the node', () => {
    const edges = [
      edge({ source: 'pos_1', target: 'pos_2' }),
      edge({ source: 'pos_1', target: 'pos_3' }),
      edge({ source: 'pos_9', target: 'pos_1' }),
    ];
    expect(resolveDirectReports(edges, 'pos_1').map((e) => e.target)).toEqual(['pos_2', 'pos_3']);
  });
});

describe('isEditableEdge', () => {
  it('is true only for employee/position origin with a real relation_id', () => {
    expect(isEditableEdge({ origin: 'position', relation_id: 5 })).toBe(true);
    expect(isEditableEdge({ origin: 'employee', relation_id: 5 })).toBe(true);
    expect(isEditableEdge({ origin: 'inferred', relation_id: null })).toBe(false);
    expect(isEditableEdge({ origin: 'position', relation_id: null })).toBe(false);
    expect(isEditableEdge({ origin: 'department', relation_id: null })).toBe(false);
  });

  it('отвергает ещё не подтверждённое сервером ребро (sentinel -1)', () => {
    expect(isEditableEdge({ origin: 'position', relation_id: OPTIMISTIC_RELATION_ID })).toBe(false);
    expect(isEditableEdge({ origin: 'employee', relation_id: 0 })).toBe(false);
  });
});

describe('applyDepartmentManagerChange', () => {
  const tree: OrgTree = {
    nodes: [
      { id: 'dept_7', label: 'ИТ', type: 'department', meta: { manager_id: 1, manager_name: 'Иван', manager_source: 'explicit' } },
      { id: 'dept_8', label: 'Финансы', type: 'department', meta: { manager_id: 2 } },
    ],
    edges: [],
  };

  it('снятие руководителя видно сразу и не трогает соседний отдел', () => {
    const next = applyDepartmentManagerChange(tree, 7, null);
    expect(next.nodes[0].meta).toMatchObject({ manager_id: null, manager_source: null });
    expect(next.nodes[1].meta).toMatchObject({ manager_id: 2 });
  });

  it('назначение проставляет explicit', () => {
    const next = applyDepartmentManagerChange(tree, 7, 42);
    expect(next.nodes[0].meta).toMatchObject({ manager_id: 42, manager_source: 'explicit' });
  });
});

describe('isValidOrgConnection', () => {
  const nodes = [node('pos_1'), node('pos_2'), node('emp_1'), node('dept_1')];

  it('rejects a missing endpoint', () => {
    expect(isValidOrgConnection(nodes, null, 'pos_1').ok).toBe(false);
  });

  it('rejects a self-connection', () => {
    const result = isValidOrgConnection(nodes, 'pos_1', 'pos_1');
    expect(result).toEqual({ ok: false, reason: 'Нельзя подчинить узел самому себе' });
  });

  it('rejects connections touching a department node', () => {
    expect(isValidOrgConnection(nodes, 'dept_1', 'pos_1').ok).toBe(false);
    expect(isValidOrgConnection(nodes, 'pos_1', 'dept_1').ok).toBe(false);
  });

  it('rejects mixing position and employee nodes', () => {
    expect(isValidOrgConnection(nodes, 'pos_1', 'emp_1').ok).toBe(false);
  });

  it('rejects a node absent from the current tree', () => {
    expect(isValidOrgConnection(nodes, 'pos_1', 'pos_999').ok).toBe(false);
  });

  it('accepts two position nodes present on the chart', () => {
    expect(isValidOrgConnection(nodes, 'pos_1', 'pos_2')).toEqual({ ok: true });
  });
});

describe('numericIdFromNodeId', () => {
  it('extracts the trailing numeric id', () => {
    expect(numericIdFromNodeId('pos_42')).toBe(42);
    expect(numericIdFromNodeId('emp_7')).toBe(7);
  });

  it('returns null for a non-numeric suffix', () => {
    expect(numericIdFromNodeId('dept_')).toBeNull();
  });
});

describe('applySuperiorChange', () => {
  it('replaces the previous editable edge of the same relation_type on the child', () => {
    const tree: OrgTree = {
      nodes: [],
      edges: [
        edge({ source: 'pos_2', target: 'pos_1', relation_type: 'direct', origin: 'position', relation_id: 10 }),
        edge({ source: 'pos_2', target: 'pos_1', relation_type: 'functional', origin: 'position', relation_id: 11 }),
      ],
    };
    const next = applySuperiorChange(tree, 'pos_3', 'pos_1', 'direct', 'position');

    expect(next.edges.some((e) => e.relation_id === 10)).toBe(false);
    expect(next.edges.some((e) => e.relation_id === 11)).toBe(true);
    const added = next.edges.find((e) => e.source === 'pos_3' && e.target === 'pos_1');
    expect(added).toMatchObject({ relation_type: 'direct', origin: 'position', relation_id: OPTIMISTIC_RELATION_ID });
  });

  it('leaves an inferred edge on the child alone', () => {
    const tree: OrgTree = {
      nodes: [],
      edges: [edge({ source: 'pos_2', target: 'pos_1', relation_type: 'direct', origin: 'inferred', relation_id: null })],
    };
    const next = applySuperiorChange(tree, 'pos_3', 'pos_1', 'direct', 'position');
    expect(next.edges).toHaveLength(2);
    expect(next.edges.some((e) => e.origin === 'inferred')).toBe(true);
  });
});

describe('applyBatchSuperiorChange', () => {
  it('attaches multiple child nodes to the parent node', () => {
    const tree: OrgTree = {
      nodes: [],
      edges: [
        edge({ source: 'pos_1', target: 'pos_2', relation_type: 'direct', origin: 'position', relation_id: 1 }),
      ],
    };
    const next = applyBatchSuperiorChange(tree, 'pos_9', ['pos_2', 'pos_3', 'pos_4'], 'direct', 'position');
    expect(next.edges.filter((e) => e.source === 'pos_9')).toHaveLength(3);
    expect(next.edges.some((e) => e.relation_id === 1)).toBe(false);
  });
});

describe('applyRelationTypeChange', () => {
  it('updates relation_type for the targeted edge', () => {
    const tree: OrgTree = {
      nodes: [],
      edges: [
        edge({ source: 'pos_1', target: 'pos_2', relation_type: 'direct', relation_id: 100 }),
        edge({ source: 'pos_1', target: 'pos_3', relation_type: 'direct', relation_id: 101 }),
      ],
    };
    const next = applyRelationTypeChange(tree, 100, 'functional');
    expect(next.edges.find((e) => e.relation_id === 100)?.relation_type).toBe('functional');
    expect(next.edges.find((e) => e.relation_id === 101)?.relation_type).toBe('direct');
  });
});

describe('resolveHierarchyChain', () => {
  it('constructs chain from root to target node', () => {
    const edges = [
      edge({ source: 'pos_ceo', target: 'pos_cto', relation_type: 'direct' }),
      edge({ source: 'pos_cto', target: 'pos_lead', relation_type: 'direct' }),
      edge({ source: 'pos_lead', target: 'pos_dev', relation_type: 'direct' }),
    ];
    const chain = resolveHierarchyChain(edges, 'pos_dev');
    expect(chain).toEqual(['pos_ceo', 'pos_cto', 'pos_lead', 'pos_dev']);
  });
});

describe('isNodeDescendant', () => {
  it('identifies descendant relationship in tree', () => {
    const edges = [
      edge({ source: 'pos_ceo', target: 'pos_cto' }),
      edge({ source: 'pos_cto', target: 'pos_dev' }),
    ];
    expect(isNodeDescendant(edges, 'pos_ceo', 'pos_dev')).toBe(true);
    expect(isNodeDescendant(edges, 'pos_dev', 'pos_ceo')).toBe(false);
  });
});

describe('removeEdgeByRelationId', () => {
  it('drops only the matching edge', () => {
    const tree: OrgTree = {
      nodes: [],
      edges: [
        edge({ source: 'a', target: 'b', relation_id: 1 }),
        edge({ source: 'c', target: 'd', relation_id: 2 }),
      ],
    };
    const next = removeEdgeByRelationId(tree, 1);
    expect(next.edges.map((e) => e.relation_id)).toEqual([2]);
  });
});

describe('collectBranch', () => {
  //        root
  //        /  \
  //      a      b
  //     / \
  //   a1   a2
  const edges = [
    { source: 'pos_root', target: 'pos_a' },
    { source: 'pos_root', target: 'pos_b' },
    { source: 'pos_a', target: 'pos_a1' },
    { source: 'pos_a', target: 'pos_a2' },
  ] as never[];

  it('берёт сам узел, всех потомков и цепочку вверх до корня', () => {
    const branch = collectBranch(edges, 'pos_a');
    expect([...branch].sort()).toEqual(['pos_a', 'pos_a1', 'pos_a2', 'pos_root']);
  });

  it('не затягивает соседнюю ветку', () => {
    expect(collectBranch(edges, 'pos_a').has('pos_b')).toBe(false);
  });

  it('у листа — он сам и предки', () => {
    expect([...collectBranch(edges, 'pos_a1')].sort()).toEqual(['pos_a', 'pos_a1', 'pos_root']);
  });

  it('у корня — всё дерево', () => {
    expect(collectBranch(edges, 'pos_root').size).toBe(5);
  });

  it('кольцо в данных не подвешивает обход', () => {
    const cyclic = [
      { source: 'pos_1', target: 'pos_2' },
      { source: 'pos_2', target: 'pos_3' },
      { source: 'pos_3', target: 'pos_1' },
    ] as never[];
    expect(collectBranch(cyclic, 'pos_1').size).toBe(3);
  });
});
