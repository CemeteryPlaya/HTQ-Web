/**
 * useOrgEditMutations — mutations behind the org-chart edit mode (панель +
 * drag&drop, см. OrgChart/index.tsx, OrgEditPanel.tsx, pages/hr/HROrgChart.tsx).
 *
 * Optimistic update + rollback on the exact react-query cache entry for the
 * currently displayed tree (treeKey — the same key HROrgChart.tsx already
 * uses: ['org-tree', mode, rootId, depth, language]), settling with a
 * broad invalidateQueries({queryKey:['org-tree']}) — the prefix-match
 * convention already established by HRPositions.tsx/PositionLevelsPanel.tsx
 * for position mutations that affect the chart.
 */
import { useQueryClient, useMutation, type QueryKey } from '@tanstack/react-query';
import { toast } from 'sonner';

import {
  createEmployeeRelation,
  createPositionRelation,
  deleteEmployeeRelation,
  deletePositionRelation,
  setDepartmentManager,
  type OrgEdge,
  type OrgEdgeOrigin,
  type OrgTree,
} from '@/api/hr';
import { reportApiError } from '@/lib/apiError';
import {
  applySuperiorChange,
  isEditableEdge,
  numericIdFromNodeId,
  removeEdgeByRelationId,
  resolveSuperiorEdge,
} from './orgEdit';

function nodeKind(nodeId: string): 'pos' | 'emp' | null {
  if (nodeId.startsWith('pos_')) return 'pos';
  if (nodeId.startsWith('emp_')) return 'emp';
  return null;
}

export function useOrgEditMutations(treeKey: QueryKey) {
  const queryClient = useQueryClient();

  const connectMutation = useMutation({
    mutationFn: async (input: { parentId: string; childId: string; relationType: string }) => {
      const parentNum = numericIdFromNodeId(input.parentId);
      const childNum = numericIdFromNodeId(input.childId);
      if (parentNum == null || childNum == null) throw new Error('Некорректный узел');
      const kind = nodeKind(input.childId);
      if (kind === 'pos') {
        return createPositionRelation({
          superior_position_id: parentNum,
          subordinate_position_id: childNum,
          relation_type: input.relationType as 'direct' | 'functional' | 'project',
        });
      }
      return createEmployeeRelation({
        superior_employee_id: parentNum,
        subordinate_employee_id: childNum,
        relation_type: input.relationType as 'direct' | 'functional' | 'project',
      });
    },
    onMutate: async (input) => {
      await queryClient.cancelQueries({ queryKey: treeKey });
      const previous = queryClient.getQueryData<OrgTree>(treeKey);
      const origin: OrgEdgeOrigin = nodeKind(input.childId) === 'pos' ? 'position' : 'employee';
      queryClient.setQueryData<OrgTree>(treeKey, (old) => (
        old ? applySuperiorChange(old, input.parentId, input.childId, input.relationType, origin) : old
      ));
      return { previous };
    },
    onError: (err, _input, context) => {
      if (context?.previous) queryClient.setQueryData(treeKey, context.previous);
      reportApiError(err, 'Не удалось изменить подчинение');
    },
    onSuccess: () => toast.success('Связь сохранена'),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['org-tree'] }),
  });

  const removeMutation = useMutation({
    mutationFn: async (edge: OrgEdge) => {
      if (edge.relation_id == null) return;
      const kind = nodeKind(edge.target);
      if (kind === 'pos') return deletePositionRelation(edge.relation_id);
      return deleteEmployeeRelation(edge.relation_id);
    },
    onMutate: async (edge) => {
      await queryClient.cancelQueries({ queryKey: treeKey });
      const previous = queryClient.getQueryData<OrgTree>(treeKey);
      if (edge.relation_id != null) {
        const relationId = edge.relation_id;
        queryClient.setQueryData<OrgTree>(treeKey, (old) => (
          old ? removeEdgeByRelationId(old, relationId) : old
        ));
      }
      return { previous };
    },
    onError: (err, _edge, context) => {
      if (context?.previous) queryClient.setQueryData(treeKey, context.previous);
      reportApiError(err, 'Не удалось убрать связь');
    },
    onSuccess: () => toast.success('Связь удалена'),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['org-tree'] }),
  });

  const setManagerMutation = useMutation({
    mutationFn: (input: { departmentId: number; employeeId: number | null }) =>
      setDepartmentManager(input.departmentId, input.employeeId),
    onSuccess: () => toast.success('Руководитель отдела обновлён'),
    onError: (err) => reportApiError(err, 'Не удалось изменить руководителя отдела'),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['org-tree'] }),
  });

  /**
   * Высокоуровневая операция "подчинить childId узлу parentId", используемая
   * и drag&drop-ом (relationType всегда "direct"), и панелью (любой тип).
   * Если у childId уже есть РЕДАКТИРУЕМЫЙ (не inferred) руководитель того же
   * типа связи — подтверждаем замену: у бэкенда не более одного прямого
   * руководителя на позицию/сотрудника, второй POST иначе вернёт 409.
   * Ничего не подтверждаем, если текущий руководитель лишь "inferred" —
   * там нет строки в БД, удалять нечего.
   */
  const connectSuperior = (parentId: string, childId: string, relationType = 'direct') => {
    const tree = queryClient.getQueryData<OrgTree>(treeKey);
    const existing = tree ? resolveSuperiorEdge(tree.edges, childId) : null;
    const mustReplace = existing && isEditableEdge(existing) && existing.relation_type === relationType;

    if (mustReplace && existing) {
      if (!window.confirm('У узла уже есть руководитель. Заменить его новым?')) return;
      removeMutation.mutate(existing, {
        onSuccess: () => connectMutation.mutate({ parentId, childId, relationType }),
      });
      return;
    }
    connectMutation.mutate({ parentId, childId, relationType });
  };

  return { connectMutation, removeMutation, setManagerMutation, connectSuperior };
}
