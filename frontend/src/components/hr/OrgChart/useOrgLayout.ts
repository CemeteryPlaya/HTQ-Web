/**
 * Applies dagre top-down layout to React Flow nodes/edges.
 * Returns new arrays with x/y positions computed.
 */
import type { Node, Edge } from '@xyflow/react';
import dagre from '@dagrejs/dagre';

const NODE_WIDTH = 210;
const NODE_HEIGHT = 168;

type Direction = 'TB' | 'LR';

export function applyDagreLayout(
  nodes: Node[],
  edges: Edge[],
  direction: Direction = 'TB',
): { nodes: Node[]; edges: Edge[] } {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({
    rankdir: direction,
    nodesep: direction === 'TB' ? 48 : 72,
    ranksep: direction === 'TB' ? 72 : 96,
  });

  for (const node of nodes) {
    g.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
  }
  for (const edge of edges) {
    g.setEdge(edge.source, edge.target);
  }

  dagre.layout(g);

  const layoutedNodes = nodes.map((node) => {
    const { x, y } = g.node(node.id);
    return {
      ...node,
      position: { x: x - NODE_WIDTH / 2, y: y - NODE_HEIGHT / 2 },
    };
  });

  return { nodes: layoutedNodes, edges };
}
