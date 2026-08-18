/**
 * OrgEditPanel — боковая панель ручной правки руководителя/прямых
 * подчинённых узла (позиция/сотрудник) или руководителя отдела. Открывается
 * вместо EmployeeDetailDrawer, когда включён режим правки на /hr/org-chart
 * (см. pages/hr/HROrgChart.tsx) — сам drawer переиспользуется и публичной
 * share-ссылкой, поэтому режим правки в него не встраивается.
 */
import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Building2, Crown, UserRound, X } from 'lucide-react';

import { fetchEmployees, fetchPositions, type OrgEdge, type OrgTree } from '@/api/hr';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import type { OrgRawNode } from './OrgChart';
import { ORIGIN_LABELS, isEditableEdge, numericIdFromNodeId, resolveDirectReports, resolveSuperiorEdge } from './orgEdit';
import type { useOrgEditMutations } from './useOrgEditMutations';

interface Props {
  node: OrgRawNode | null;
  tree: OrgTree | undefined;
  onClose: () => void;
  mutations: ReturnType<typeof useOrgEditMutations>;
}

type RelationType = 'direct' | 'functional' | 'project';

const RELATION_LABELS: Record<RelationType, string> = {
  direct: 'Прямое',
  functional: 'Функциональное',
  project: 'Проектное',
};

function metaString(meta: Record<string, unknown> | undefined, key: string): string | null {
  const v = meta?.[key];
  return typeof v === 'string' && v.trim() ? v : null;
}

function edgeLabel(edge: OrgEdge, names: Map<string, string>): string {
  return names.get(edge.source) ?? edge.source;
}

export function OrgEditPanel({ node, tree, onClose, mutations }: Props) {
  const edges = tree?.edges ?? [];
  const nodeId = node?.id ?? null;
  const isPosition = node?.type === 'position';
  const isDepartment = node?.type === 'department';
  const isEmployee = node?.type === 'employee';

  const [pickedSuperior, setPickedSuperior] = useState('');
  const [relationType, setRelationType] = useState<RelationType>('direct');
  const [pickedReport, setPickedReport] = useState('');
  const [pickedManager, setPickedManager] = useState('');

  useEffect(() => {
    setPickedSuperior('');
    setRelationType('direct');
    setPickedReport('');
    setPickedManager(metaString(node?.meta, 'manager_id') ?? '');
    // Сбрасываем форму только при смене УЗЛА, не при любом обновлении его
    // meta — иначе фоновый рефетч дерева (мутация соседнего узла, invalidate
    // по таймеру) стирал бы то, что пользователь только начал выбирать.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodeId]);

  const positionsQuery = useQuery({
    queryKey: ['hr-positions-v1'],
    queryFn: fetchPositions,
    enabled: isPosition,
    staleTime: 60_000,
  });
  const employeesQuery = useQuery({
    queryKey: ['hr-employees-list'],
    queryFn: () => fetchEmployees(),
    enabled: isEmployee || isDepartment,
    staleTime: 60_000,
  });

  // id узла ("pos_42"/"emp_7") -> человекочитаемое имя, для подписи под
  // "Руководитель"/списком подчинённых без лишних запросов.
  const nodeNames = useMemo(() => {
    const map = new Map<string, string>();
    for (const n of tree?.nodes ?? []) map.set(n.id, n.label);
    return map;
  }, [tree]);

  if (!node) {
    return (
      <Sheet open={false} onOpenChange={(o) => !o && onClose()}>
        <SheetContent />
      </Sheet>
    );
  }

  const superiorEdge = nodeId ? resolveSuperiorEdge(edges, nodeId) : null;
  const reports = nodeId ? resolveDirectReports(edges, nodeId) : [];
  const prefix = isEmployee ? 'emp_' : 'pos_';
  const candidates = isEmployee ? (employeesQuery.data ?? []) : (positionsQuery.data ?? []);
  const currentNumericId = nodeId ? numericIdFromNodeId(nodeId) : null;

  const superiorCandidateOptions = candidates
    .filter((c) => c.id !== currentNumericId)
    .map((c) => ({
      id: c.id,
      label: isEmployee
        ? (c as { full_name?: string; email: string }).full_name || (c as { email: string }).email
        : (c as { title: string }).title,
    }));

  const handleAssignSuperior = () => {
    if (!nodeId || !pickedSuperior) return;
    mutations.connectSuperior(`${prefix}${pickedSuperior}`, nodeId, relationType);
    setPickedSuperior('');
  };

  const handleAddReport = () => {
    if (!nodeId || !pickedReport) return;
    mutations.connectSuperior(nodeId, `${prefix}${pickedReport}`, 'direct');
    setPickedReport('');
  };

  const departmentId = isDepartment && nodeId ? numericIdFromNodeId(nodeId) : null;
  const managerSource = metaString(node.meta, 'manager_source');
  const managerName = metaString(node.meta, 'manager_name');

  const handleSaveManager = () => {
    if (departmentId == null) return;
    mutations.setManagerMutation.mutate({
      departmentId, employeeId: pickedManager ? Number(pickedManager) : null,
    });
  };

  const handleClearManager = () => {
    if (departmentId == null) return;
    mutations.setManagerMutation.mutate({ departmentId, employeeId: null });
    setPickedManager('');
  };

  return (
    <Sheet open={Boolean(node)} onOpenChange={(o) => !o && onClose()}>
      <SheetContent
        side="right"
        className="!inset-x-0 !bottom-0 !top-auto !h-[85dvh] !w-full overflow-y-auto rounded-t-xl border-t p-4 pb-[calc(1rem+env(safe-area-inset-bottom))] sm:!inset-y-0 sm:!left-auto sm:!right-0 sm:!h-full sm:!w-[420px] sm:max-w-[480px] sm:rounded-none sm:border-l sm:border-t-0 sm:p-6"
      >
        <SheetHeader>
          <SheetTitle className="text-left">{node.label}</SheetTitle>
          <SheetDescription className="text-left">
            {isDepartment ? 'Отдел' : isEmployee ? 'Сотрудник' : 'Должность'} · редактирование связей
          </SheetDescription>
        </SheetHeader>

        <div className="mt-5 space-y-6">
          {isDepartment && (
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-sm font-semibold">
                <Building2 className="h-4 w-4" /> Руководитель отдела
              </div>
              {managerName && (
                <div className="flex items-center gap-2 text-sm">
                  <Crown className="h-3.5 w-3.5 text-muted-foreground" />
                  <span>{managerName}</span>
                  {managerSource && (
                    <Badge variant="outline" className="text-[10px]">
                      {managerSource === 'explicit' ? 'задан вручную' : 'определён автоматически'}
                    </Badge>
                  )}
                </div>
              )}
              <div className="flex gap-2">
                <Select value={pickedManager} onValueChange={setPickedManager}>
                  <SelectTrigger className="h-8 flex-1">
                    <SelectValue placeholder="Выбрать сотрудника" />
                  </SelectTrigger>
                  <SelectContent>
                    {(employeesQuery.data ?? []).map((e) => (
                      <SelectItem key={e.id} value={String(e.id)}>
                        {e.full_name || e.email}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button
                  size="sm"
                  disabled={!pickedManager || mutations.setManagerMutation.isPending}
                  onClick={handleSaveManager}
                >
                  Сохранить
                </Button>
              </div>
              {managerSource === 'explicit' && (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={mutations.setManagerMutation.isPending}
                  onClick={handleClearManager}
                >
                  Очистить
                </Button>
              )}
            </div>
          )}

          {(isPosition || isEmployee) && (
            <>
              <div className="space-y-2">
                <div className="flex items-center gap-2 text-sm font-semibold">
                  <UserRound className="h-4 w-4" /> Руководитель
                </div>
                {superiorEdge ? (
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <span>{edgeLabel(superiorEdge, nodeNames)}</span>
                    <Badge variant="outline" className="text-[10px]">
                      {ORIGIN_LABELS[superiorEdge.origin]}
                    </Badge>
                    {isEditableEdge(superiorEdge) && (
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-6 px-1.5 text-xs text-destructive"
                        disabled={mutations.removeMutation.isPending}
                        onClick={() => mutations.removeMutation.mutate(superiorEdge)}
                      >
                        <X className="mr-1 h-3 w-3" /> Убрать
                      </Button>
                    )}
                  </div>
                ) : (
                  <p className="text-xs text-muted-foreground">Руководитель не определён.</p>
                )}
                <div className="flex flex-wrap gap-2">
                  <Select value={pickedSuperior} onValueChange={setPickedSuperior}>
                    <SelectTrigger className="h-8 flex-1 min-w-[160px]">
                      <SelectValue placeholder="Выбрать руководителя" />
                    </SelectTrigger>
                    <SelectContent>
                      {superiorCandidateOptions.map((c) => (
                        <SelectItem key={c.id} value={String(c.id)}>{c.label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Select value={relationType} onValueChange={(v) => setRelationType(v as RelationType)}>
                    <SelectTrigger className="h-8 w-36">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {(Object.keys(RELATION_LABELS) as RelationType[]).map((rt) => (
                        <SelectItem key={rt} value={rt}>{RELATION_LABELS[rt]}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Button
                    size="sm"
                    disabled={!pickedSuperior || mutations.connectMutation.isPending}
                    onClick={handleAssignSuperior}
                  >
                    Назначить
                  </Button>
                </div>
              </div>

              <div className="space-y-2 border-t pt-4">
                <div className="text-sm font-semibold">Прямые подчинённые</div>
                {reports.length === 0 && (
                  <p className="text-xs text-muted-foreground">Подчинённых нет.</p>
                )}
                <ul className="space-y-1.5">
                  {reports.map((r) => (
                    <li key={`${r.source}-${r.target}-${r.relation_type}`} className="flex items-center justify-between gap-2 rounded-md border px-2.5 py-1.5 text-xs">
                      <div className="min-w-0 flex-1 truncate">{nodeNames.get(r.target) ?? r.target}</div>
                      <Badge variant="outline" className="text-[10px]">{ORIGIN_LABELS[r.origin]}</Badge>
                      {isEditableEdge(r) && (
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-6 px-1.5 text-destructive"
                          disabled={mutations.removeMutation.isPending}
                          onClick={() => mutations.removeMutation.mutate(r)}
                        >
                          <X className="h-3 w-3" />
                        </Button>
                      )}
                    </li>
                  ))}
                </ul>
                <div className="flex gap-2">
                  <Select value={pickedReport} onValueChange={setPickedReport}>
                    <SelectTrigger className="h-8 flex-1">
                      <SelectValue placeholder="Добавить подчинённого" />
                    </SelectTrigger>
                    <SelectContent>
                      {superiorCandidateOptions.map((c) => (
                        <SelectItem key={c.id} value={String(c.id)}>{c.label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={!pickedReport || mutations.connectMutation.isPending}
                    onClick={handleAddReport}
                  >
                    Добавить
                  </Button>
                </div>
              </div>

              {isEmployee && (
                <p className="text-xs text-muted-foreground">
                  Персональное подчинение переопределяет связь, выведенную из должностей.
                </p>
              )}
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
