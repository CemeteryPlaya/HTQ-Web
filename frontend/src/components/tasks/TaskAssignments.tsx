import React from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { toast } from 'sonner';
import { Users, User, Truck, X } from 'lucide-react';
import {
  fetchAssignments, createAssignment, deleteAssignment, fetchEquipment,
} from '@/api/tasks';
import { fetchEmployeeUsers } from '@/api/hr';

interface Props {
  taskId: number;
}

/**
 * Управление ресурсами задачи: сотрудники + техника (many-to-many).
 * Питает ресурсную диаграмму Ганта (/tasks/resources).
 */
export const TaskAssignments: React.FC<Props> = ({ taskId }) => {
  const qc = useQueryClient();

  const { data: assignments = [] } = useQuery({
    queryKey: ['assignments', taskId],
    queryFn: () => fetchAssignments(taskId),
  });
  const { data: users = [] } = useQuery({
    queryKey: ['hr-users'],
    queryFn: () => fetchEmployeeUsers(),
  });
  const { data: equipment = [] } = useQuery({
    queryKey: ['equipment'],
    queryFn: () => fetchEquipment(true),
  });

  const userMap = new Map(users.map((u) => [u.id, u.full_name]));
  const eqMap = new Map(equipment.map((e) => [e.id, e.name]));

  const empAssign = assignments.filter((a) => a.employee_id != null);
  const eqAssign = assignments.filter((a) => a.equipment_id != null);

  const assignedEmp = new Set(empAssign.map((a) => a.employee_id));
  const assignedEq = new Set(eqAssign.map((a) => a.equipment_id));
  const availUsers = users.filter((u) => !assignedEmp.has(u.id));
  const availEquipment = equipment.filter((e) => !assignedEq.has(e.id));

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['assignments', taskId] });
    qc.invalidateQueries({ queryKey: ['resource-gantt'] });
  };
  const addMut = useMutation({
    mutationFn: createAssignment,
    onSuccess: invalidate,
    onError: () => toast.error('Не удалось назначить ресурс'),
  });
  const delMut = useMutation({
    mutationFn: deleteAssignment,
    onSuccess: invalidate,
    onError: () => toast.error('Не удалось снять назначение'),
  });

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-sm flex items-center gap-2">
          <Users className="h-4 w-4" /> Ресурсы задачи
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Сотрудники */}
        <div>
          <div className="text-xs uppercase text-muted-foreground mb-1.5 flex items-center gap-1">
            <User className="h-3 w-3" /> Сотрудники
          </div>
          <div className="flex flex-wrap gap-1.5 mb-2">
            {empAssign.length === 0 && <span className="text-xs text-muted-foreground">Не назначены</span>}
            {empAssign.map((a) => (
              <Badge key={a.id} variant="secondary" className="gap-1 pr-1">
                {userMap.get(a.employee_id!) ?? `#${a.employee_id}`}
                <button type="button" onClick={() => delMut.mutate(a.id)} className="hover:text-destructive">
                  <X className="h-3 w-3" />
                </button>
              </Badge>
            ))}
          </div>
          <Select value="" onValueChange={(v) => addMut.mutate({ task_id: taskId, employee_id: Number(v) })}>
            <SelectTrigger className="h-8 text-xs">
              <SelectValue placeholder="+ добавить сотрудника" />
            </SelectTrigger>
            <SelectContent>
              {availUsers.length === 0
                ? <div className="px-2 py-1.5 text-xs text-muted-foreground">Все добавлены</div>
                : availUsers.map((u) => <SelectItem key={u.id} value={String(u.id)}>{u.full_name}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>

        {/* Техника */}
        <div>
          <div className="text-xs uppercase text-muted-foreground mb-1.5 flex items-center gap-1">
            <Truck className="h-3 w-3" /> Техника
          </div>
          <div className="flex flex-wrap gap-1.5 mb-2">
            {eqAssign.length === 0 && <span className="text-xs text-muted-foreground">Не назначена</span>}
            {eqAssign.map((a) => (
              <Badge key={a.id} variant="outline" className="gap-1 pr-1">
                {eqMap.get(a.equipment_id!) ?? `#${a.equipment_id}`}
                <button type="button" onClick={() => delMut.mutate(a.id)} className="hover:text-destructive">
                  <X className="h-3 w-3" />
                </button>
              </Badge>
            ))}
          </div>
          <Select value="" onValueChange={(v) => addMut.mutate({ task_id: taskId, equipment_id: Number(v) })}>
            <SelectTrigger className="h-8 text-xs">
              <SelectValue placeholder="+ добавить технику" />
            </SelectTrigger>
            <SelectContent>
              {availEquipment.length === 0
                ? <div className="px-2 py-1.5 text-xs text-muted-foreground">Нет доступной техники</div>
                : availEquipment.map((e) => <SelectItem key={e.id} value={String(e.id)}>{e.name}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
      </CardContent>
    </Card>
  );
};

export default TaskAssignments;
