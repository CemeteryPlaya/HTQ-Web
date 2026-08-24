/**
 * OrgEditPanel — современная боковая панель ручной правки руководителя и
 * прямых подчинённых узла (позиция/сотрудник) или руководителя отдела.
 */
import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  AlertCircle,
  BriefcaseBusiness,
  Building2,
  ChevronRight,
  Crown,
  GitBranch,
  Mail,
  Phone,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  UserCheck,
  UserMinus,
  UserPlus,
  Users,
  X,
} from 'lucide-react';

import {
  fetchEmployees,
  fetchPositions,
  type OrgEdge,
  type OrgTree,
  type RelationType,
} from '@/api/hr';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Sheet,
  SheetContent,
} from '@/components/ui/sheet';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import type { OrgRawNode } from './OrgChart';
import {
  ORIGIN_LABELS,
  isEditableEdge,
  isNodeDescendant,
  isValidOrgConnection,
  numericIdFromNodeId,
  resolveDirectReports,
  resolveHierarchyChain,
  resolveSuperiorEdge,
} from './orgEdit';
import type { useOrgEditMutations } from './useOrgEditMutations';
import { EntityCombobox, type EntityOption } from './EntityCombobox';
import { TransferSubordinatesDialog } from './TransferSubordinatesDialog';
import { translatedMap } from '@/lib/i18n/translatedMap';
import { useTranslation } from 'react-i18next';

interface Props {
  node: OrgRawNode | null;
  tree: OrgTree | undefined;
  onClose: () => void;
  onSelectNode?: (nodeId: string) => void;
  mutations: ReturnType<typeof useOrgEditMutations>;
}

const RELATION_LABELS: Record<RelationType, string> = translatedMap({
  direct: 'hr.orgChart.relation.direct',
  functional: 'hr.orgChart.relation.functional',
  project: 'hr.orgChart.relation.project',
});

const RELATION_BADGE_STYLES: Record<RelationType, string> = {
  direct: 'border-slate-400 bg-slate-100 text-slate-800 dark:bg-slate-900 dark:text-slate-200',
  functional: 'border-blue-400 bg-blue-50 text-blue-800 dark:bg-blue-950 dark:text-blue-200',
  project: 'border-amber-400 bg-amber-50 text-amber-800 dark:bg-amber-950 dark:text-amber-200',
};

function metaString(meta: Record<string, unknown> | undefined, key: string): string | null {
  const v = meta?.[key];
  return typeof v === 'string' && v.trim() ? v : null;
}

function metaNumber(meta: Record<string, unknown> | undefined, key: string): number | null {
  const v = meta?.[key];
  return typeof v === 'number' && Number.isFinite(v) ? v : null;
}

function getInitials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return '?';
  const first = parts[0]?.[0] ?? '';
  const last = parts.length > 1 ? parts[parts.length - 1]?.[0] ?? '' : '';
  return (first + last).toUpperCase() || '?';
}

export function OrgEditPanel({
  node,
  tree,
  onClose,
  onSelectNode,
  mutations,
}: Props) {
  const { t } = useTranslation();
  const edges = tree?.edges ?? [];
  const nodes = tree?.nodes ?? [];
  const nodeId = node?.id ?? null;
  const isPosition = node?.type === 'position';
  const isDepartment = node?.type === 'department';
  const isEmployee = node?.type === 'employee';

  // Forms state
  const [pickedSuperior, setPickedSuperior] = useState('');
  const [superiorRelationType, setSuperiorRelationType] = useState<RelationType>('direct');
  const [showChangeSuperior, setShowChangeSuperior] = useState(false);

  const [pickedReports, setPickedReports] = useState<string[]>([]);
  const [reportsRelationType, setReportsRelationType] = useState<RelationType>('direct');
  const [subordinateSearch, setSubordinateSearch] = useState('');

  const [pickedManager, setPickedManager] = useState('');
  const [panelError, setPanelError] = useState<string | null>(null);

  const [transferDialogOpen, setTransferDialogOpen] = useState(false);

  useEffect(() => {
    setPickedSuperior('');
    setSuperiorRelationType('direct');
    setShowChangeSuperior(false);
    setPickedReports([]);
    setReportsRelationType('direct');
    setSubordinateSearch('');
    setPickedManager(metaString(node?.meta, 'manager_id') ?? '');
    setPanelError(null);
  }, [nodeId]);

  const positionsQuery = useQuery({
    queryKey: ['hr-positions-v1'],
    queryFn: fetchPositions,
    enabled: isPosition,
    staleTime: 60_000,
  });

  const employeesQuery = useQuery({
    queryKey: ['hr-employees-list', 'org-editor-200'],
    queryFn: () => fetchEmployees({ limit: '200' }),
    enabled: isEmployee || isDepartment,
    staleTime: 60_000,
  });

  const nodeMap = useMemo(() => {
    const map = new Map<string, OrgRawNode>();
    for (const n of nodes) map.set(n.id, n);
    return map;
  }, [nodes]);

  const nodeNames = useMemo(() => {
    const map = new Map<string, string>();
    for (const n of nodes) map.set(n.id, n.label);
    return map;
  }, [nodes]);

  const superiorEdge = useMemo(
    () => (nodeId ? resolveSuperiorEdge(edges, nodeId) : null),
    [edges, nodeId]
  );

  const reports = useMemo(
    () => (nodeId ? resolveDirectReports(edges, nodeId) : []),
    [edges, nodeId]
  );

  const prefix = isEmployee ? 'emp_' : 'pos_';
  const currentNumericId = nodeId ? numericIdFromNodeId(nodeId) : null;

  // Hierarchy chain from top leader to this node
  const hierarchyChain = useMemo(
    () => (nodeId ? resolveHierarchyChain(edges, nodeId) : []),
    [edges, nodeId]
  );

  // Options list for EntityCombobox
  const candidateOptions: EntityOption[] = useMemo(() => {
    if (isEmployee) {
      return (employeesQuery.data ?? []).map((e) => ({
        id: e.id,
        label: e.full_name || e.email,
        subLabel: e.position_title ?? undefined,
        departmentName: e.department_name ?? undefined,
        avatarUrl: e.avatar_url ?? undefined,
        type: 'employee' as const,
      }));
    }
    return (positionsQuery.data ?? []).map((p) => ({
      id: p.id,
      label: p.title,
      subLabel: p.department?.name ?? undefined,
      departmentName: p.department?.name ?? undefined,
      level: p.level ?? undefined,
      grade: p.grade ?? undefined,
      type: 'position' as const,
    }));
  }, [isEmployee, employeesQuery.data, positionsQuery.data]);

  // Options for Superior (exclude self and direct/transitive subordinates to prevent cycles)
  const superiorOptions = useMemo(() => {
    return candidateOptions.filter((c) => {
      if (c.id === currentNumericId) return false;
      const candNodeId = `${prefix}${c.id}`;
      if (nodeId && isNodeDescendant(edges, nodeId, candNodeId)) return false;
      return true;
    });
  }, [candidateOptions, currentNumericId, prefix, nodeId, edges]);

  // Options for Subordinates (exclude self and already assigned subordinates)
  const subordinateOptions = useMemo(() => {
    const existingReportIds = new Set(reports.map((r) => numericIdFromNodeId(r.target)));
    return candidateOptions.filter(
      (c) => c.id !== currentNumericId && !existingReportIds.has(c.id)
    );
  }, [candidateOptions, reports, currentNumericId]);

  // Filtered reports
  const filteredReports = useMemo(() => {
    if (!subordinateSearch.trim()) return reports;
    const q = subordinateSearch.toLowerCase();
    return reports.filter((r) => {
      const name = nodeNames.get(r.target) ?? r.target;
      return name.toLowerCase().includes(q);
    });
  }, [reports, subordinateSearch, nodeNames]);

  if (!node) {
    return (
      <Sheet open={false} onOpenChange={(o) => !o && onClose()}>
        <SheetContent />
      </Sheet>
    );
  }

  const guard = (sourceId: string, targetId: string): boolean => {
    const check = isValidOrgConnection(nodes, sourceId, targetId);
    if (!check.ok) {
      setPanelError(check.reason);
      return false;
    }
    setPanelError(null);
    return true;
  };

  const handleAssignSuperior = () => {
    if (!nodeId || !pickedSuperior) return;
    const sourceId = `${prefix}${pickedSuperior}`;
    if (!guard(sourceId, nodeId)) return;
    mutations.connectSuperior(sourceId, nodeId, superiorRelationType);
    setPickedSuperior('');
    setShowChangeSuperior(false);
  };

  const handleAddReports = async () => {
    if (!nodeId || pickedReports.length === 0) return;
    const targetIds = pickedReports.map((id) => `${prefix}${id}`);
    for (const targetId of targetIds) {
      if (!guard(nodeId, targetId)) return;
    }
    if (targetIds.length === 1) {
      mutations.connectSuperior(nodeId, targetIds[0], reportsRelationType);
    } else {
      await mutations.batchAddReportsMutation.mutateAsync({
        parentId: nodeId,
        childIds: targetIds,
        relationType: reportsRelationType,
      });
    }
    setPickedReports([]);
  };

  const handleChangeRelationType = (edge: OrgEdge, newType: RelationType) => {
    if (!isEditableEdge(edge)) return;
    mutations.changeTypeMutation.mutate({ edge, newType });
  };

  const handleTransferSubordinates = async (targetManagerId: string, subIds: string[]) => {
    await mutations.transferSubordinatesMutation.mutateAsync({
      targetManagerId,
      subordinateIds: subIds,
    });
  };

  const departmentId = isDepartment && nodeId ? numericIdFromNodeId(nodeId) : null;
  const managerName = metaString(node.meta, 'manager_name');
  const managerSource = metaString(node.meta, 'manager_source');
  const managerAvatarUrl = metaString(node.meta, 'manager_avatar_url');

  const handleSaveManager = () => {
    if (departmentId == null) return;
    mutations.setManagerMutation.mutate({
      departmentId,
      employeeId: pickedManager ? Number(pickedManager) : null,
    });
  };

  const handleClearManager = () => {
    if (departmentId == null) return;
    mutations.setManagerMutation.mutate({ departmentId, employeeId: null });
    setPickedManager('');
  };

  // Node details for Hero Header
  const nodeTitle = node.label;
  const nodeDept = metaString(node.meta, 'department_name');
  const nodePosition = metaString(node.meta, 'position_title');
  const nodeLevel = metaNumber(node.meta, 'level');
  const nodeGrade = metaNumber(node.meta, 'grade');
  const nodeAvatarUrl =
    metaString(node.meta, 'avatar_url') || metaString(node.meta, 'holder_avatar_url');
  const nodeEmail = metaString(node.meta, 'email') || metaString(node.meta, 'holder_email');
  const nodePhone = metaString(node.meta, 'phone') || metaString(node.meta, 'holder_phone');

  return (
    <>
      <Sheet open={Boolean(node)} onOpenChange={(o) => !o && onClose()}>
        <SheetContent
          side="right"
          className="!inset-x-0 !bottom-0 !top-auto !h-[90dvh] !w-full overflow-y-auto rounded-t-2xl border-t p-0 pb-[calc(1.5rem+env(safe-area-inset-bottom))] sm:!inset-y-0 sm:!left-auto sm:!right-0 sm:!h-full sm:!w-[460px] sm:max-w-[500px] sm:rounded-none sm:border-l sm:border-t-0 flex flex-col bg-background"
        >
          {/* Hero Header */}
          <div className="relative border-b bg-gradient-to-br from-primary/10 via-background to-muted/40 p-5 sm:p-6 pb-4">
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-3.5 min-w-0">
                {nodeAvatarUrl ? (
                  <img
                    src={nodeAvatarUrl}
                    alt=""
                    className="h-14 w-14 rounded-full object-cover ring-2 ring-background shadow-md shrink-0"
                  />
                ) : (
                  <div className="flex h-14 w-14 items-center justify-center rounded-full bg-gradient-to-br from-primary/20 to-primary/5 text-primary ring-2 ring-background shadow-md shrink-0">
                    {isDepartment ? (
                      <Building2 className="h-6 w-6 text-primary" />
                    ) : isPosition ? (
                      <BriefcaseBusiness className="h-6 w-6 text-primary" />
                    ) : (
                      <span className="text-base font-bold">{getInitials(nodeTitle)}</span>
                    )}
                  </div>
                )}

                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <Badge variant="outline" className="text-[10px] uppercase font-bold tracking-wider px-1.5 py-0">
                      {isDepartment ? t('hr.card.department') : isEmployee ? t('hr.orgChart.employee') : t('hr.card.position')}
                    </Badge>
                    {nodeLevel != null && (
                      <Badge variant="secondary" className="text-[10px] px-1.5 py-0 font-medium">
                        {t('hr.orgChart.panel.levelBadge', { level: nodeLevel })}
                      </Badge>
                    )}
                    {nodeGrade != null && (
                      <Badge variant="secondary" className="text-[10px] px-1.5 py-0 font-medium">
                        {t('hr.orgChart.panel.gradeBadge', { grade: nodeGrade })}
                      </Badge>
                    )}
                  </div>

                  <h2 className="text-base sm:text-lg font-bold text-foreground truncate mt-1 leading-tight" title={nodeTitle}>
                    {nodeTitle}
                  </h2>

                  {(nodePosition || nodeDept) && (
                    <p className="text-xs text-muted-foreground truncate leading-tight mt-0.5">
                      {[nodePosition, nodeDept].filter(Boolean).join(' · ')}
                    </p>
                  )}
                </div>
              </div>
            </div>

            {/* Contact quick links */}
            {(nodeEmail || nodePhone) && (
              <div className="flex items-center gap-3 mt-3 pt-2.5 border-t border-border/50 text-xs text-muted-foreground">
                {nodeEmail && (
                  <a href={`mailto:${nodeEmail}`} className="flex items-center gap-1 hover:text-foreground truncate transition-colors">
                    <Mail className="h-3.5 w-3.5 shrink-0" />
                    <span className="truncate">{nodeEmail}</span>
                  </a>
                )}
                {nodePhone && (
                  <a href={`tel:${nodePhone}`} className="flex items-center gap-1 hover:text-foreground truncate transition-colors">
                    <Phone className="h-3.5 w-3.5 shrink-0" />
                    <span className="truncate">{nodePhone}</span>
                  </a>
                )}
              </div>
            )}

            {/* Breadcrumb Hierarchy Path */}
            {hierarchyChain.length > 1 && (
              <div className="mt-3 pt-2.5 border-t border-border/50">
                <div className="flex items-center gap-1 text-[11px] text-muted-foreground font-medium mb-1">
                  <GitBranch className="h-3 w-3" />
                  <span>{t('hr.orgChart.panel.chain')}</span>
                </div>
                <div className="flex items-center gap-1 overflow-x-auto pb-1 text-xs text-muted-foreground scrollbar-none">
                  {hierarchyChain.map((cId, idx) => {
                    const cNode = nodeMap.get(cId);
                    const isLast = idx === hierarchyChain.length - 1;
                    return (
                      <div key={cId} className="flex items-center gap-1 shrink-0">
                        {idx > 0 && <ChevronRight className="h-3 w-3 opacity-40 shrink-0" />}
                        <button
                          type="button"
                          onClick={() => onSelectNode?.(cId)}
                          className={`truncate max-w-[120px] rounded px-1.5 py-0.5 text-[11px] transition-colors ${
                            isLast
                              ? 'bg-primary/10 text-primary font-bold'
                              : 'hover:bg-muted text-foreground/80 hover:text-foreground'
                          }`}
                          title={cNode?.label ?? cId}
                        >
                          {cNode?.label ?? cId}
                        </button>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>

          {/* Main Content Area */}
          <div className="flex-1 overflow-y-auto p-4 sm:p-6 space-y-6">
            {panelError && (
              <div
                role="alert"
                className="flex items-start gap-2.5 rounded-xl border border-destructive/40 bg-destructive/10 p-3 text-xs text-destructive animate-in fade-in"
              >
                <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
                <div className="flex-1 min-w-0 font-medium leading-relaxed">{panelError}</div>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-5 w-5 p-0 text-destructive hover:bg-destructive/20"
                  onClick={() => setPanelError(null)}
                >
                  <X className="h-3.5 w-3.5" />
                </Button>
              </div>
            )}

            {/* Department Manager View */}
            {isDepartment && (
              <div className="space-y-3 rounded-xl border bg-card p-4 shadow-xs">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-sm font-bold text-foreground">
                    <Building2 className="h-4 w-4 text-primary" />
                    {t('hr.orgChart.panel.departmentHead')}
                  </div>
                  {managerSource && (
                    <Badge variant="outline" className="text-[10px] font-normal">
                      {managerSource === 'explicit' ? t('hr.orgChart.origin.employee') : t('hr.orgChart.origin.inferred')}
                    </Badge>
                  )}
                </div>

                {managerName ? (
                  <div className="flex items-center justify-between gap-3 rounded-lg border bg-muted/40 p-3">
                    <div className="flex items-center gap-2.5 min-w-0">
                      {managerAvatarUrl ? (
                        <img src={managerAvatarUrl} alt="" className="h-9 w-9 rounded-full object-cover" />
                      ) : (
                        <span className="flex h-9 w-9 items-center justify-center rounded-full bg-primary/10 text-xs font-bold text-primary">
                          {getInitials(managerName)}
                        </span>
                      )}
                      <div className="min-w-0">
                        <div className="font-semibold text-xs text-foreground truncate">{managerName}</div>
                        <div className="text-[11px] text-muted-foreground">{t('hr.orgChart.panel.unitHead')}</div>
                      </div>
                    </div>

                    {managerSource === 'explicit' && (
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-7 text-xs text-destructive hover:bg-destructive/10"
                        disabled={mutations.setManagerMutation.isPending}
                        onClick={handleClearManager}
                      >
                        <UserMinus className="h-3.5 w-3.5 mr-1" />
                        {t('hr.orgChart.panel.unassign')}
                      </Button>
                    )}
                  </div>
                ) : (
                  <div className="rounded-lg border border-dashed p-3 text-center text-xs text-muted-foreground">
                    {t('hr.orgChart.panel.noManagerAssigned')}
                  </div>
                )}

                <div className="space-y-2 pt-2 border-t">
                  <label className="text-xs font-semibold text-foreground">
                    {managerName ? t('hr.orgChart.changeDeptHead') : t('hr.orgChart.assignDeptHead')}
                  </label>
                  <div className="flex gap-2">
                    <div className="flex-1 min-w-0">
                      <EntityCombobox
                        mode="single"
                        value={pickedManager}
                        onChange={setPickedManager}
                        options={(employeesQuery.data ?? []).map((e) => ({
                          id: e.id,
                          label: e.full_name || e.email,
                          subLabel: e.position_title ?? undefined,
                          departmentName: e.department_name ?? undefined,
                          avatarUrl: e.avatar_url ?? undefined,
                          type: 'employee',
                        }))}
                        placeholder={t('hr.orgChart.panel.pickEmployee')}
                        searchPlaceholder={t('hr.orgChart.panel.searchEmployee')}
                      />
                    </div>
                    <Button
                      size="sm"
                      disabled={!pickedManager || mutations.setManagerMutation.isPending}
                      onClick={handleSaveManager}
                      className="gap-1"
                    >
                      <UserCheck className="h-3.5 w-3.5" />
                      {t('common.save')}
                    </Button>
                  </div>
                </div>
              </div>
            )}

            {/* Position & Employee Superior / Subordinates Editor */}
            {(isPosition || isEmployee) && (
              <>
                {/* SECTION 1: Руководитель (Manager) */}
                <div className="space-y-3 rounded-xl border bg-card p-4 shadow-xs">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2 text-sm font-bold text-foreground">
                      <Crown className="h-4 w-4 text-amber-500" />
                      {t('hr.orgChart.manager')}
                    </div>
                    {superiorEdge && (
                      <Badge
                        variant="outline"
                        className={`text-[10px] font-semibold ${
                          RELATION_BADGE_STYLES[superiorEdge.relation_type as RelationType] || ''
                        }`}
                      >
                        {RELATION_LABELS[superiorEdge.relation_type as RelationType] || superiorEdge.relation_type}
                      </Badge>
                    )}
                  </div>

                  {superiorEdge ? (
                    <div className="space-y-2.5">
                      <div className="flex items-center justify-between gap-3 rounded-lg border bg-muted/40 p-3">
                        <div className="flex items-center gap-2.5 min-w-0">
                          <span className="flex h-9 w-9 items-center justify-center rounded-full bg-amber-500/10 text-xs font-bold text-amber-600 dark:text-amber-400">
                            {getInitials(nodeNames.get(superiorEdge.source) ?? superiorEdge.source)}
                          </span>
                          <div className="min-w-0">
                            <div className="font-semibold text-xs text-foreground truncate">
                              {nodeNames.get(superiorEdge.source) ?? superiorEdge.source}
                            </div>
                            <div className="text-[11px] text-muted-foreground">
                              {ORIGIN_LABELS[superiorEdge.origin]}
                            </div>
                          </div>
                        </div>

                        {/* Actions for current superior */}
                        {isEditableEdge(superiorEdge) && (
                          <div className="flex items-center gap-1 shrink-0">
                            {/* Inline relation type changer */}
                            <DropdownMenu>
                              <DropdownMenuTrigger asChild>
                                <Button variant="outline" size="sm" className="h-7 text-xs px-2 gap-1">
                                  {t('hr.orgChart.panel.relationTypeValue', {
                                    type: RELATION_LABELS[superiorEdge.relation_type as RelationType]
                                      || t('hr.orgChart.relation.direct'),
                                  })}
                                </Button>
                              </DropdownMenuTrigger>
                              <DropdownMenuContent align="end">
                                {(Object.keys(RELATION_LABELS) as RelationType[]).map((rt) => (
                                  <DropdownMenuItem
                                    key={rt}
                                    onClick={() => handleChangeRelationType(superiorEdge, rt)}
                                    className="text-xs"
                                  >
                                    {RELATION_LABELS[rt]}
                                  </DropdownMenuItem>
                                ))}
                              </DropdownMenuContent>
                            </DropdownMenu>

                            <Button
                              size="sm"
                              variant="ghost"
                              className="h-7 w-7 p-0 text-destructive hover:bg-destructive/10"
                              title={t('hr.orgChart.panel.removeManager')}
                              disabled={mutations.removeMutation.isPending}
                              onClick={() => {
                                if (window.confirm(t('hr.orgChart.panel.confirmRemoveManager'))) {
                                  mutations.removeMutation.mutate(superiorEdge);
                                }
                              }}
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </Button>
                          </div>
                        )}
                      </div>

                      {/* Quick change superior button toggle */}
                      {!showChangeSuperior ? (
                        <Button
                          size="sm"
                          variant="ghost"
                          className="w-full text-xs text-muted-foreground hover:text-foreground h-7"
                          onClick={() => setShowChangeSuperior(true)}
                        >
                          <RefreshCw className="h-3 w-3 mr-1.5" />
                          {t('hr.orgChart.panel.changeManager')}
                        </Button>
                      ) : (
                        <div className="space-y-2 pt-2 border-t">
                          <div className="flex items-center justify-between">
                            <span className="text-xs font-semibold text-foreground">{t('hr.orgChart.newManager')}</span>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-5 px-1.5 text-[11px] text-muted-foreground"
                              onClick={() => setShowChangeSuperior(false)}
                            >
                              {t('common.cancel')}
                            </Button>
                          </div>
                          <div className="space-y-2">
                            <EntityCombobox
                              mode="single"
                              value={pickedSuperior}
                              onChange={setPickedSuperior}
                              options={superiorOptions}
                              placeholder={t('hr.orgChart.panel.pickManager')}
                              searchPlaceholder={t('hr.orgChart.panel.search')}
                            />
                            <div className="flex items-center gap-2">
                              <Select
                                value={superiorRelationType}
                                onValueChange={(v) => setSuperiorRelationType(v as RelationType)}
                              >
                                <SelectTrigger className="h-8 flex-1 text-xs">
                                  <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                  {(Object.keys(RELATION_LABELS) as RelationType[]).map((rt) => (
                                    <SelectItem key={rt} value={rt} className="text-xs">
                                      {RELATION_LABELS[rt]}
                                    </SelectItem>
                                  ))}
                                </SelectContent>
                              </Select>
                              <Button
                                size="sm"
                                disabled={!pickedSuperior || mutations.connectMutation.isPending}
                                onClick={handleAssignSuperior}
                                className="h-8 text-xs"
                              >
                                {t('hr.orgChart.panel.assign')}
                              </Button>
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  ) : (
                    /* When there is no supervisor assigned */
                    <div className="space-y-3">
                      <div className="rounded-lg border border-dashed p-3 text-center text-xs text-muted-foreground">
                        {t('hr.orgChart.panel.noManagerResolved')}
                      </div>
                      <div className="space-y-2">
                        <EntityCombobox
                          mode="single"
                          value={pickedSuperior}
                          onChange={setPickedSuperior}
                          options={superiorOptions}
                          placeholder={t('hr.orgChart.panel.assignManager')}
                          searchPlaceholder={t('hr.orgChart.searchManager')}
                        />
                        <div className="flex items-center gap-2">
                          <Select
                            value={superiorRelationType}
                            onValueChange={(v) => setSuperiorRelationType(v as RelationType)}
                          >
                            <SelectTrigger className="h-8 flex-1 text-xs">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              {(Object.keys(RELATION_LABELS) as RelationType[]).map((rt) => (
                                <SelectItem key={rt} value={rt} className="text-xs">
                                  {RELATION_LABELS[rt]}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                          <Button
                            size="sm"
                            disabled={!pickedSuperior || mutations.connectMutation.isPending}
                            onClick={handleAssignSuperior}
                            className="h-8 text-xs"
                          >
                            {t('hr.orgChart.panel.assign')}
                          </Button>
                        </div>
                      </div>
                    </div>
                  )}
                </div>

                {/* SECTION 2: Прямые подчинённые (Subordinates) */}
                <div className="space-y-3 rounded-xl border bg-card p-4 shadow-xs">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2 text-sm font-bold text-foreground">
                      <Users className="h-4 w-4 text-primary" />
                      {t('hr.orgChart.panel.directReports')}
                      <Badge variant="secondary" className="text-[10px] px-1.5 py-0 font-semibold">
                        {reports.length}
                      </Badge>
                    </div>

                    {reports.length > 0 && (
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-7 text-xs gap-1"
                        onClick={() => setTransferDialogOpen(true)}
                      >
                        <UserCheck className="h-3 w-3" />
                        {t('hr.orgChart.panel.transfer')}
                      </Button>
                    )}
                  </div>

                  {/* Filter when there are multiple subordinates */}
                  {reports.length > 3 && (
                    <div className="relative">
                      <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
                      <input
                        value={subordinateSearch}
                        onChange={(e) => setSubordinateSearch(e.target.value)}
                        placeholder={t('hr.orgChart.panel.filterReports')}
                        className="h-8 w-full rounded-md border bg-muted/30 pl-8 pr-3 text-xs outline-none focus:border-primary"
                      />
                    </div>
                  )}

                  {/* Subordinates List */}
                  {reports.length === 0 ? (
                    <div className="rounded-lg border border-dashed p-3 text-center text-xs text-muted-foreground">
                      {t('hr.orgChart.panel.noReports')}
                    </div>
                  ) : (
                    <div className="space-y-1.5 max-h-[220px] overflow-y-auto p-0.5">
                      {filteredReports.map((r) => {
                        const targetName = nodeNames.get(r.target) ?? r.target;
                        const editable = isEditableEdge(r);
                        return (
                          <div
                            key={`${r.source}-${r.target}-${r.relation_type}`}
                            className="flex items-center justify-between gap-2 rounded-lg border bg-muted/20 hover:bg-muted/50 p-2 text-xs transition-colors"
                          >
                            <div className="flex items-center gap-2 min-w-0 flex-1">
                              <span className="flex h-7 w-7 items-center justify-center rounded-full bg-primary/10 text-[10px] font-bold text-primary shrink-0">
                                {getInitials(targetName)}
                              </span>
                              <div className="min-w-0 flex-1">
                                <div className="truncate font-semibold text-foreground" title={targetName}>
                                  {targetName}
                                </div>
                                <div className="text-[10px] text-muted-foreground">
                                  {ORIGIN_LABELS[r.origin]}
                                </div>
                              </div>
                            </div>

                            <div className="flex items-center gap-1 shrink-0">
                              {editable ? (
                                <DropdownMenu>
                                  <DropdownMenuTrigger asChild>
                                    <Button
                                      variant="ghost"
                                      size="sm"
                                      className="h-6 text-[10px] px-1.5 font-medium border"
                                    >
                                      {RELATION_LABELS[r.relation_type as RelationType] || r.relation_type}
                                    </Button>
                                  </DropdownMenuTrigger>
                                  <DropdownMenuContent align="end">
                                    {(Object.keys(RELATION_LABELS) as RelationType[]).map((rt) => (
                                      <DropdownMenuItem
                                        key={rt}
                                        onClick={() => handleChangeRelationType(r, rt)}
                                        className="text-xs"
                                      >
                                        {RELATION_LABELS[rt]}
                                      </DropdownMenuItem>
                                    ))}
                                  </DropdownMenuContent>
                                </DropdownMenu>
                              ) : (
                                <Badge variant="outline" className="text-[10px] px-1 py-0 h-5 font-normal">
                                  {RELATION_LABELS[r.relation_type as RelationType] || r.relation_type}
                                </Badge>
                              )}

                              {editable && (
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  className="h-6 w-6 p-0 text-destructive hover:bg-destructive/10"
                                  title={t('hr.orgChart.panel.removeReport')}
                                  disabled={mutations.removeMutation.isPending}
                                  onClick={() => {
                                    if (window.confirm(t('hr.orgChart.panel.confirmRemoveReport', { name: targetName }))) {
                                      mutations.removeMutation.mutate(r);
                                    }
                                  }}
                                >
                                  <Trash2 className="h-3 w-3" />
                                </Button>
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}

                  {/* Add Subordinates Form */}
                  <div className="space-y-2 pt-3 border-t">
                    <label className="text-xs font-semibold text-foreground flex items-center gap-1.5">
                      <UserPlus className="h-3.5 w-3.5 text-primary" />
                      {t('hr.orgChart.panel.addReports')}
                    </label>
                    <EntityCombobox
                      mode="multi"
                      value={pickedReports}
                      onChange={setPickedReports}
                      options={subordinateOptions}
                      placeholder={t('hr.orgChart.panel.pickEntities')}
                      searchPlaceholder={t('hr.orgChart.panel.searchToAdd')}
                    />
                    <div className="flex items-center gap-2">
                      <Select
                        value={reportsRelationType}
                        onValueChange={(v) => setReportsRelationType(v as RelationType)}
                      >
                        <SelectTrigger className="h-8 flex-1 text-xs">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {(Object.keys(RELATION_LABELS) as RelationType[]).map((rt) => (
                            <SelectItem key={rt} value={rt} className="text-xs">
                              {RELATION_LABELS[rt]}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <Button
                        size="sm"
                        disabled={
                          pickedReports.length === 0 ||
                          mutations.connectMutation.isPending ||
                          mutations.batchAddReportsMutation.isPending
                        }
                        onClick={handleAddReports}
                        className="h-8 text-xs gap-1"
                      >
                        <Plus className="h-3.5 w-3.5" />
                        {pickedReports.length > 1
                          ? t('hr.orgChart.panel.addWithCount', { count: pickedReports.length })
                          : t('common.add')}
                      </Button>
                    </div>
                  </div>
                </div>
              </>
            )}
          </div>
        </SheetContent>
      </Sheet>

      {/* Transfer Subordinates Dialog */}
      <TransferSubordinatesDialog
        open={transferDialogOpen}
        onClose={() => setTransferDialogOpen(false)}
        currentNode={node}
        reports={reports}
        candidateOptions={candidateOptions}
        nodeNames={nodeNames}
        onTransfer={handleTransferSubordinates}
        isLoading={mutations.transferSubordinatesMutation.isPending}
      />
    </>
  );
}
