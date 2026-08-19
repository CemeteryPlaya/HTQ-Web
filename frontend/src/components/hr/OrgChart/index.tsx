/**
 * OrgChart — interactive company org-chart using React Flow + dagre layout.
 * Supports positions / employees / both modes; PNG/SVG export; level filter.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  useReactFlow,
  ConnectionLineType,
  Position,
  type Connection,
  type Node,
  type Edge,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { toPng, toSvg } from 'html-to-image';
import { toast } from 'sonner';

import type { OrgEdge, OrgEdgeOrigin, OrgNode, RelationType } from '@/api/hr';
import { OrgChartNode } from './OrgChartNode';
import { collectBranch, isValidOrgConnection, resolveSuperiorEdge } from './orgEdit';
import { applyDagreLayout } from './useOrgLayout';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { ConnectDialog } from './ConnectDialog';

const nodeTypes = { orgNode: OrgChartNode };

type RawNode = OrgNode;

// PMO's /pmo/{id}/org-chart edges carry only {source,target,relation_type} —
// no relation_id/origin (those are org/tree-specific). Widened here so the
// same component serves both without either caller lying about the shape.
type RawEdge = Omit<OrgEdge, 'relation_id' | 'origin'> & {
  relation_id?: number | null;
  origin?: OrgEdgeOrigin;
};

type Direction = 'TB' | 'LR';

interface OrgChartProps {
  rawNodes: RawNode[];
  rawEdges: RawEdge[];
  maxLevelFilter?: number;
  isLoading?: boolean;
  hideToolbar?: boolean;
  compact?: boolean;
  showMiniMap?: boolean;
  onNodeClick?: (node: RawNode) => void;
  editable?: boolean;
  onConnectNodes?: (
    sourceId: string,
    targetId: string,
    relationType?: RelationType,
    note?: string
  ) => void;
}

export type { RawNode as OrgRawNode };

const EDGE_STYLE: Record<string, { stroke: string; strokeDasharray?: string }> = {
  direct: { stroke: '#64748b' },
  functional: { stroke: '#3b82f6', strokeDasharray: '6 3' },
  project: { stroke: '#f59e0b', strokeDasharray: '3 3' },
  structural: { stroke: '#94a3b8' },
  membership: { stroke: '#cbd5e1' },
  employment: { stroke: '#cbd5e1' },
};

const INFERRED_EDGE_STYLE = { strokeDasharray: '2 4', opacity: 0.55 };

function buildFlowElements(
  rawNodes: RawNode[],
  rawEdges: RawEdge[],
  levelFilter: number | null,
  direction: Direction,
  editable: boolean,
  /** Узел, от которого сейчас тянут связь. Пока тянут — остальные карточки
   *  помечаются как валидная/невалидная цель, чтобы бросать вслепую не
   *  приходилось. null — перетаскивания нет. */
  connectSource: string | null = null,
): { nodes: Node[]; edges: Edge[] } {
  const visibleIds = new Set(
    rawNodes
      .filter((n) => levelFilter == null || (n.level == null || n.level <= levelFilter))
      .map((n) => n.id),
  );

  // Compute reportsCount per node for badge in OrgChartNode
  const reportsCountMap = new Map<string, number>();
  for (const e of rawEdges) {
    if (visibleIds.has(e.source) && visibleIds.has(e.target)) {
      reportsCountMap.set(e.source, (reportsCountMap.get(e.source) ?? 0) + 1);
    }
  }

  const nodes: Node[] = rawNodes
    .filter((n) => visibleIds.has(n.id))
    .map((n) => ({
      id: n.id,
      type: 'orgNode',
      position: { x: 0, y: 0 },
      targetPosition: direction === 'LR' ? Position.Left : Position.Top,
      sourcePosition: direction === 'LR' ? Position.Right : Position.Bottom,
      data: {
        label: n.label,
        type: n.type,
        unit_type: n.unit_type,
        level: n.level,
        weight: n.weight,
        direction,
        meta: n.meta,
        editable,
        reportsCount: reportsCountMap.get(n.id) ?? 0,
        dropState: connectSource == null || connectSource === n.id
          ? null
          : (isValidOrgConnection(rawNodes, connectSource, n.id).ok ? 'valid' : 'invalid'),
      },
    }));

  const edges: Edge[] = rawEdges
    .filter((e) => visibleIds.has(e.source) && visibleIds.has(e.target))
    .map((e) => {
      const isInferred = e.origin === 'inferred';
      return {
        id: `${e.source}->${e.target}-${e.relation_type}-${e.relation_id ?? 'x'}`,
        source: e.source,
        target: e.target,
        type: 'step',
        style: {
          ...(EDGE_STYLE[e.relation_type] ?? EDGE_STYLE.structural),
          ...(isInferred ? INFERRED_EDGE_STYLE : null),
          strokeWidth: 2,
        },
        data: { relationId: e.relation_id ?? null, origin: e.origin ?? null },
        animated: false,
        focusable: editable,
        // Перетаскивать конец можно только у настоящей связи: у выведенной
        // (inferred) строки в БД нет, переподчинять нечего.
        reconnectable: editable && !isInferred && e.relation_id != null && e.relation_id > 0,
        interactionWidth: 16,
      };
    });

  return applyDagreLayout(nodes, edges, direction);
}

export function OrgChart({
  rawNodes,
  rawEdges,
  maxLevelFilter,
  isLoading,
  hideToolbar = false,
  compact = false,
  showMiniMap = true,
  onNodeClick,
  editable = false,
  onConnectNodes,
}: OrgChartProps) {
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [levelFilter, setLevelFilter] = useState<number | null>(maxLevelFilter ?? null);
  const [direction, setDirection] = useState<Direction>('TB');
  const { fitView } = useReactFlow();
  const containerRef = useRef<HTMLDivElement>(null);

  // Connect dialog state
  const [pendingConnection, setPendingConnection] = useState<{
    sourceId: string;
    targetId: string;
    /** Переподчинение существующей связи: её надо снять после создания новой. */
    replacingEdgeId?: number | null;
  } | null>(null);

  /** Узел-источник, пока пользователь тянет связь (для подсветки целей). */
  const [connectSource, setConnectSource] = useState<string | null>(null);

  // ── Фокус на ветке ────────────────────────────────────────────────────
  // hovered — временная подсветка под курсором; pinned — зафиксированная
  // кнопкой в тулбаре, чтобы ветку можно было разглядывать, убрав мышь.
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);
  const [pinnedNode, setPinnedNode] = useState<string | null>(null);
  const focusNodeId = pinnedNode ?? hoveredNode;

  const nodeMap = useMemo(() => {
    const map = new Map<string, RawNode>();
    for (const n of rawNodes) map.set(n.id, n);
    return map;
  }, [rawNodes]);

  const maxLevel = Math.max(
    1,
    ...rawNodes.map((n) => n.level ?? 0),
  );

  useEffect(() => {
    if (maxLevelFilter !== undefined) {
      setLevelFilter(maxLevelFilter);
    }
  }, [maxLevelFilter]);

  useEffect(() => {
    const { nodes: n, edges: e } = buildFlowElements(
      rawNodes, rawEdges, levelFilter, direction, editable, connectSource,
    );
    setNodes(n);
    setEdges(e);
  }, [rawNodes, rawEdges, levelFilter, direction, editable, connectSource]);

  useEffect(() => {
    const t = setTimeout(() => fitView({ padding: 0.15, duration: 300 }), 50);
    return () => clearTimeout(t);
  }, [levelFilter, direction, fitView]);

  // Подсветка ветки накладывается ПОВЕРХ готовой раскладки: только data и
  // style, без повторного прогона dagre. Иначе схема пересобиралась бы на
  // каждое движение мыши.
  useEffect(() => {
    const branch = focusNodeId ? collectBranch(rawEdges, focusNodeId) : null;

    setNodes((prev) => prev.map((n) => {
      const state = branch ? (branch.has(n.id) ? 'in' : 'out') : null;
      const data = n.data as { branchState?: string | null };
      if ((data.branchState ?? null) === state) return n;
      return { ...n, data: { ...n.data, branchState: state } };
    }));

    setEdges((prev) => prev.map((e) => {
      const inBranch = branch ? (branch.has(e.source) && branch.has(e.target)) : null;
      const style = {
        ...e.style,
        opacity: inBranch === false ? 0.12 : (e.style?.opacity ?? 1),
        strokeWidth: inBranch === true ? 3 : 2,
      };
      return { ...e, style, animated: inBranch === true && e.data?.origin !== 'inferred' };
    }));
  }, [focusNodeId, rawEdges, rawNodes, levelFilter, direction, editable, connectSource, setNodes, setEdges]);

  const handleConnect = useCallback((connection: Connection) => {
    if (!onConnectNodes) return;
    const check = isValidOrgConnection(rawNodes, connection.source, connection.target);
    if (!check.ok) {
      toast.error(check.reason);
      return;
    }
    setPendingConnection({
      sourceId: connection.source as string,
      targetId: connection.target as string,
    });
  }, [onConnectNodes, rawNodes]);

  const handleConfirmConnection = useCallback((relationType: RelationType, note?: string) => {
    if (!pendingConnection || !onConnectNodes) return;
    onConnectNodes(pendingConnection.sourceId, pendingConnection.targetId, relationType, note);
    setPendingConnection(null);
  }, [pendingConnection, onConnectNodes]);

  const handleConnectStart = useCallback((_e: unknown, params: { nodeId?: string | null }) => {
    setConnectSource(params.nodeId ?? null);
  }, []);

  const handleConnectEnd = useCallback(() => setConnectSource(null), []);

  /**
   * Перетаскивание КОНЦА существующей связи на другого руководителя.
   * Новая связь создаётся атомарной ручкой PUT .../superior, которая сама
   * снимает прежнюю, поэтому отдельного удаления не нужно.
   */
  const handleReconnect = useCallback((oldEdge: Edge, connection: Connection) => {
    if (!onConnectNodes) return;
    const check = isValidOrgConnection(rawNodes, connection.source, connection.target);
    if (!check.ok) {
      toast.error(check.reason);
      return;
    }
    if (oldEdge.source === connection.source && oldEdge.target === connection.target) return;
    setPendingConnection({
      sourceId: connection.source as string,
      targetId: connection.target as string,
      replacingEdgeId: (oldEdge.data as { relationId?: number | null } | undefined)?.relationId ?? null,
    });
  }, [onConnectNodes, rawNodes]);

  const isValidConnection = useCallback((connection: Connection | Edge) => {
    const source = 'source' in connection ? connection.source : null;
    const target = 'target' in connection ? connection.target : null;
    return isValidOrgConnection(rawNodes, source, target).ok;
  }, [rawNodes]);

  const exportPng = useCallback(async () => {
    if (!containerRef.current) return;
    const dataUrl = await toPng(containerRef.current, { backgroundColor: '#ffffff' });
    const a = document.createElement('a');
    a.href = dataUrl;
    a.download = 'org-chart.png';
    a.click();
  }, []);

  const exportSvg = useCallback(async () => {
    if (!containerRef.current) return;
    const dataUrl = await toSvg(containerRef.current, { backgroundColor: '#ffffff' });
    const a = document.createElement('a');
    a.href = dataUrl;
    a.download = 'org-chart.svg';
    a.click();
  }, []);

  // Details for pending connection dialog
  const sourceNode = pendingConnection ? nodeMap.get(pendingConnection.sourceId) ?? null : null;
  const targetNode = pendingConnection ? nodeMap.get(pendingConnection.targetId) ?? null : null;
  const existingSuperiorEdge = targetNode
    ? resolveSuperiorEdge(rawEdges as OrgEdge[], targetNode.id)
    : null;
  const existingSuperiorName = existingSuperiorEdge
    ? nodeMap.get(existingSuperiorEdge.source)?.label ?? existingSuperiorEdge.source
    : null;

  return (
    <div className={`flex h-full min-h-0 flex-col ${hideToolbar ? 'gap-0' : 'gap-3'}`}>
      {/* Control panel */}
      {!hideToolbar && (
        <div className="flex flex-wrap items-center gap-2 px-1">
          <div className="flex items-center gap-1.5 text-sm">
            <span className="text-muted-foreground">Глубина:</span>
            <Select
              value={levelFilter == null ? 'all' : String(levelFilter)}
              onValueChange={(v) => setLevelFilter(v === 'all' ? null : parseInt(v))}
            >
              <SelectTrigger className="h-8 w-24">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Все</SelectItem>
                {Array.from({ length: maxLevel }, (_, i) => i + 1).map((l) => (
                  <SelectItem key={l} value={String(l)}>до L{l}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="flex items-center gap-1.5 text-sm">
            <span className="text-muted-foreground">Направление:</span>
            <Select value={direction} onValueChange={(v) => setDirection(v as Direction)}>
              <SelectTrigger className="h-8 w-28">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="TB">Сверху вниз</SelectItem>
                <SelectItem value="LR">Слева направо</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <Button size="sm" variant="outline" onClick={() => fitView({ padding: 0.15, duration: 300 })}>
            По экрану
          </Button>
          <Button size="sm" variant="outline" onClick={exportPng}>PNG</Button>
          <Button size="sm" variant="outline" onClick={exportSvg}>SVG</Button>

          {/* Legend */}
          <div className="ml-auto flex items-center gap-3 text-xs text-muted-foreground">
            <span className="flex items-center gap-1">
              <span className="inline-block w-6 h-0.5 bg-slate-500" /> прямое
            </span>
            <span className="flex items-center gap-1">
              <span className="inline-block w-6 h-0.5 border-t-2 border-dashed border-blue-400" /> функциональное
            </span>
            <span className="flex items-center gap-1">
              <span className="inline-block w-6 h-0.5 border-t-2 border-dotted border-amber-400" /> проектное
            </span>
            <span className="flex items-center gap-1 opacity-55">
              <span className="inline-block w-6 h-0.5 border-t-2 border-dashed border-slate-400" /> выведено автоматически
            </span>
          </div>
        </div>
      )}

      {/* Graph canvas */}
      <div
        ref={containerRef}
        className={`min-h-0 flex-1 rounded-xl border bg-background shadow-inner ${compact ? '' : 'min-h-[500px]'}`}
      >
        {isLoading ? (
          <div className="flex h-full items-center justify-center text-muted-foreground text-sm">
            Загрузка структуры…
          </div>
        ) : (
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onNodeClick={onNodeClick ? (_, n) => {
              const raw = rawNodes.find((r) => r.id === n.id);
              if (raw) onNodeClick(raw);
            } : undefined}
            onNodeMouseEnter={(_, n) => setHoveredNode(n.id)}
            onNodeMouseLeave={() => setHoveredNode(null)}
            onConnect={editable ? handleConnect : undefined}
            onConnectStart={editable ? handleConnectStart : undefined}
            onConnectEnd={editable ? handleConnectEnd : undefined}
            onReconnect={editable ? handleReconnect : undefined}
            edgesReconnectable={editable}
            reconnectRadius={18}
            connectionLineStyle={{ stroke: '#0ea5e9', strokeWidth: 2.5, strokeDasharray: '6 3' }}
            isValidConnection={editable ? isValidConnection : undefined}
            nodeTypes={nodeTypes}
            connectionLineType={ConnectionLineType.Step}
            defaultEdgeOptions={{ type: 'step' }}
            fitView
            minZoom={0.1}
            maxZoom={2}
            proOptions={{ hideAttribution: true }}
            nodesDraggable={false}
            nodesConnectable={editable}
          >
            <Controls position="bottom-right" />
            {showMiniMap && <MiniMap zoomable pannable className={compact ? 'hidden md:block' : undefined} />}
            <Background gap={16} size={1} />
          </ReactFlow>
        )}
      </div>

      {/* Connect Dialog on Handle Drop */}
      <ConnectDialog
        open={Boolean(pendingConnection)}
        onClose={() => setPendingConnection(null)}
        sourceNode={sourceNode}
        targetNode={targetNode}
        currentSuperiorName={existingSuperiorName}
        onConfirm={handleConfirmConnection}
      />
    </div>
  );
}
