import { describe, expect, it } from 'vitest';

import type { OrgEdge, OrgNode, OrgTree } from '@/api/hr';
import {
  applySuperiorChange,
  isEditableEdge,
  isValidOrgConnection,
  numericIdFromNodeId,
  OPTIMISTIC_RELATION_ID,
  removeEdgeByRelationId,
  resolveDirectReports,
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

    // old direct edge (10) replaced, functional edge (11) untouched
    expect(next.edges.some((e) => e.relation_id === 10)).toBe(false);
    expect(next.edges.some((e) => e.relation_id === 11)).toBe(true);
    const added = next.edges.find((e) => e.source === 'pos_3' && e.target === 'pos_1');
    expect(added).toMatchObject({ relation_type: 'direct', origin: 'position', relation_id: OPTIMISTIC_RELATION_ID });
  });

  it('leaves an inferred edge on the child alone (nothing to delete server-side)', () => {
    const tree: OrgTree = {
      nodes: [],
      edges: [edge({ source: 'pos_2', target: 'pos_1', relation_type: 'direct', origin: 'inferred', relation_id: null })],
    };
    const next = applySuperiorChange(tree, 'pos_3', 'pos_1', 'direct', 'position');
    expect(next.edges).toHaveLength(2);
    expect(next.edges.some((e) => e.origin === 'inferred')).toBe(true);
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
