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
  changeEmployeeRelationType,
  changePositionRelationType,
  createEmployeeRelation,
  deleteEmployeeRelation,
  deletePositionRelation,
  setDepartmentManager,
  setEmployeeSuperior,
  setPositionSuperior,
  type OrgEdge,
  type OrgEdgeOrigin,
  type OrgTree,
  type RelationType,
} from '@/api/hr';
import { reportApiError } from '@/lib/apiError';
import i18next from '@/i18n';
import {
  applyBatchSuperiorChange,
  applyDepartmentManagerChange,
  applyRelationTypeChange,
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
    mutationFn: async (input: {
      parentId: string;
      childId: string;
      relationType: string;
      note?: string;
    }) => {
      const parentNum = numericIdFromNodeId(input.parentId);
      const childNum = numericIdFromNodeId(input.childId);
      if (parentNum == null || childNum == null) throw new Error(i18next.t('hr.orgChart.errors.badNode'));

      const isPos = nodeKind(input.childId) === 'pos';

      // For employees, if there is a note or non-direct type, createEmployeeRelation can be used
      // For standard direct replacement, setEmployeeSuperior / setPositionSuperior is ideal
      if (isPos) {
        return setPositionSuperior({
          subordinate_id: childNum,
          superior_id: parentNum,
          relation_type: input.relationType as RelationType,
        });
      }

      // If note is provided for employee relation, we can call createEmployeeRelation or setEmployeeSuperior
      if (input.note) {
        try {
          return await setEmployeeSuperior({
            subordinate_id: childNum,
            superior_id: parentNum,
            relation_type: input.relationType as RelationType,
          });
        } catch {
          return await createEmployeeRelation({
            superior_employee_id: parentNum,
            subordinate_employee_id: childNum,
            relation_type: input.relationType as RelationType,
            note: input.note,
          });
        }
      }

      return setEmployeeSuperior({
        subordinate_id: childNum,
        superior_id: parentNum,
        relation_type: input.relationType as RelationType,
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
      reportApiError(err, i18next.t('hr.orgChart.errors.changeReporting'));
    },
    onSuccess: () => toast.success(i18next.t('hr.orgChart.linkSaved')),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['org-tree'] }),
  });

  const changeTypeMutation = useMutation({
    mutationFn: async (input: { edge: OrgEdge; newType: RelationType }) => {
      const relationId = input.edge.relation_id;
      if (relationId == null) throw new Error(i18next.t('hr.orgChart.errors.implicitLink'));
      const kind = nodeKind(input.edge.target);
      if (kind === 'pos') {
        return changePositionRelationType(relationId, input.newType);
      }
      return changeEmployeeRelationType(relationId, input.newType);
    },
    onMutate: async (input) => {
      await queryClient.cancelQueries({ queryKey: treeKey });
      const previous = queryClient.getQueryData<OrgTree>(treeKey);
      if (input.edge.relation_id != null) {
        const relationId = input.edge.relation_id;
        queryClient.setQueryData<OrgTree>(treeKey, (old) => (
          old ? applyRelationTypeChange(old, relationId, input.newType) : old
        ));
      }
      return { previous };
    },
    onError: (err, _input, context) => {
      if (context?.previous) queryClient.setQueryData(treeKey, context.previous);
      reportApiError(err, i18next.t('hr.orgChart.errors.changeLinkType'));
    },
    onSuccess: () => toast.success(i18next.t('hr.orgChart.linkTypeUpdated')),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['org-tree'] }),
  });

  const batchAddReportsMutation = useMutation({
    mutationFn: async (input: {
      parentId: string;
      childIds: string[];
      relationType: RelationType;
    }) => {
      const parentNum = numericIdFromNodeId(input.parentId);
      if (parentNum == null) throw new Error(i18next.t('hr.orgChart.errors.badManager'));
      const isPos = nodeKind(input.parentId) === 'pos';

      const results = await Promise.all(
        input.childIds.map(async (childId) => {
          const childNum = numericIdFromNodeId(childId);
          if (childNum == null) return null;
          return isPos
            ? setPositionSuperior({
                subordinate_id: childNum,
                superior_id: parentNum,
                relation_type: input.relationType,
              })
            : setEmployeeSuperior({
                subordinate_id: childNum,
                superior_id: parentNum,
                relation_type: input.relationType,
              });
        })
      );
      return results;
    },
    onMutate: async (input) => {
      await queryClient.cancelQueries({ queryKey: treeKey });
      const previous = queryClient.getQueryData<OrgTree>(treeKey);
      const origin: OrgEdgeOrigin = nodeKind(input.parentId) === 'pos' ? 'position' : 'employee';
      queryClient.setQueryData<OrgTree>(treeKey, (old) => (
        old ? applyBatchSuperiorChange(old, input.parentId, input.childIds, input.relationType, origin) : old
      ));
      return { previous };
    },
    onError: (err, _input, context) => {
      if (context?.previous) queryClient.setQueryData(treeKey, context.previous);
      reportApiError(err, i18next.t('hr.orgChart.errors.addReports'));
    },
    onSuccess: (_, input) => {
      toast.success(i18next.t('hr.orgChart.reportsAdded', { count: input.childIds.length }));
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['org-tree'] }),
  });

  const transferSubordinatesMutation = useMutation({
    mutationFn: async (input: {
      targetManagerId: string;
      subordinateIds: string[];
      relationType?: RelationType;
    }) => {
      const targetManagerNum = numericIdFromNodeId(input.targetManagerId);
      if (targetManagerNum == null) throw new Error(i18next.t('hr.orgChart.errors.badTargetManager'));
      const isPos = nodeKind(input.targetManagerId) === 'pos';
      const relType = input.relationType || 'direct';

      const results = await Promise.all(
        input.subordinateIds.map(async (childId) => {
          const childNum = numericIdFromNodeId(childId);
          if (childNum == null) return null;
          return isPos
            ? setPositionSuperior({
                subordinate_id: childNum,
                superior_id: targetManagerNum,
                relation_type: relType,
              })
            : setEmployeeSuperior({
                subordinate_id: childNum,
                superior_id: targetManagerNum,
                relation_type: relType,
              });
        })
      );
      return results;
    },
    onMutate: async (input) => {
      await queryClient.cancelQueries({ queryKey: treeKey });
      const previous = queryClient.getQueryData<OrgTree>(treeKey);
      const origin: OrgEdgeOrigin = nodeKind(input.targetManagerId) === 'pos' ? 'position' : 'employee';
      queryClient.setQueryData<OrgTree>(treeKey, (old) => (
        old ? applyBatchSuperiorChange(old, input.targetManagerId, input.subordinateIds, input.relationType || 'direct', origin) : old
      ));
      return { previous };
    },
    onError: (err, _input, context) => {
      if (context?.previous) queryClient.setQueryData(treeKey, context.previous);
      reportApiError(err, i18next.t('hr.orgChart.errors.transferReports'));
    },
    onSuccess: (_, input) => {
      toast.success(i18next.t('hr.orgChart.reportsTransferred', { count: input.subordinateIds.length }));
    },
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
      reportApiError(err, i18next.t('hr.orgChart.errors.removeLink'));
    },
    onSuccess: () => toast.success(i18next.t('hr.orgChart.linkRemoved')),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['org-tree'] }),
  });

  const setManagerMutation = useMutation({
    mutationFn: (input: { departmentId: number; employeeId: number | null }) =>
      setDepartmentManager(input.departmentId, input.employeeId),
    onMutate: async (input) => {
      await queryClient.cancelQueries({ queryKey: treeKey });
      const previous = queryClient.getQueryData<OrgTree>(treeKey);
      queryClient.setQueryData<OrgTree>(treeKey, (old) => (
        old ? applyDepartmentManagerChange(old, input.departmentId, input.employeeId) : old
      ));
      return { previous };
    },
    onError: (err, _input, context) => {
      if (context?.previous) queryClient.setQueryData(treeKey, context.previous);
      reportApiError(err, i18next.t('hr.orgChart.errors.changeDeptHead'));
    },
    onSuccess: () => toast.success(i18next.t('hr.orgChart.deptHeadUpdated')),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['org-tree'] }),
  });

  /**
   * Высокоуровневая операция "подчинить childId узлу parentId".
   */
  const connectSuperior = (
    parentId: string,
    childId: string,
    relationType = 'direct',
    note?: string,
    skipConfirm = false,
  ) => {
    const tree = queryClient.getQueryData<OrgTree>(treeKey);
    const existing = tree ? resolveSuperiorEdge(tree.edges, childId) : null;
    const mustReplace = Boolean(
      existing && isEditableEdge(existing) && existing.relation_type === relationType,
    );

    if (mustReplace && !skipConfirm) {
      if (!window.confirm(i18next.t('hr.orgChart.confirmReplaceManager'))) return;
    }
    connectMutation.mutate({ parentId, childId, relationType, note });
  };

  return {
    connectMutation,
    removeMutation,
    setManagerMutation,
    changeTypeMutation,
    batchAddReportsMutation,
    transferSubordinatesMutation,
    connectSuperior,
  };
}
