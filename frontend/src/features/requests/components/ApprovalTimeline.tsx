/** Status timeline card. Phase 7b will render the full activity log + per-
 *  step approver list once we expose those via the API. */

import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';

import type { RequestInstance } from '@/features/requests/types';

const STATUS_VARIANT: Record<
  RequestInstance['status'],
  { label: string; className: string }
> = {
  draft:     { label: 'Черновик',        className: 'bg-slate-200 text-slate-700 hover:bg-slate-200' },
  pending:   { label: 'На согласовании', className: 'bg-amber-100 text-amber-800 hover:bg-amber-100' },
  approved:  { label: 'Одобрен',         className: 'bg-emerald-100 text-emerald-800 hover:bg-emerald-100' },
  rejected:  { label: 'Отклонён',        className: 'bg-rose-100 text-rose-800 hover:bg-rose-100' },
  cancelled: { label: 'Отменён',         className: 'bg-slate-200 text-slate-700 hover:bg-slate-200' },
  returned:  { label: 'На доработке',    className: 'bg-blue-100 text-blue-800 hover:bg-blue-100' },
};

interface Props {
  instance: RequestInstance;
}

export function ApprovalTimeline({ instance }: Props) {
  const status = STATUS_VARIANT[instance.status];
  const fmt = (d: string | null) => (d ? new Date(d).toLocaleString('ru-RU') : '—');
  return (
    <Card>
      <CardContent className="space-y-3 py-4">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline" className={status.className}>{status.label}</Badge>
          {instance.current_node_id && (
            <span className="text-xs text-muted-foreground">шаг «{instance.current_node_id}»</span>
          )}
          {instance.requires_admin_attention && (
            <Badge variant="outline" className="bg-orange-100 text-orange-800 hover:bg-orange-100">
              требуется внимание администратора
            </Badge>
          )}
        </div>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <dt>Создан:</dt><dd>{fmt(instance.created_at)}</dd>
          <dt>Отправлен:</dt><dd>{fmt(instance.submitted_at)}</dd>
          <dt>Завершён:</dt><dd>{fmt(instance.finalized_at)}</dd>
          <dt>Инициатор:</dt><dd>#{instance.initiator_id}</dd>
        </dl>
      </CardContent>
    </Card>
  );
}
