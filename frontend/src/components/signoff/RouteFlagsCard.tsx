/**
 * «Правила маршрута» — флаги маршрута согласования (мастер-план БЗО, D-21).
 *
 * Все выключены по умолчанию: маршрут без них работает как раньше. Флаги
 * снимком уходят в процесс при отправке — правка здесь не меняет уже идущие
 * согласования. «Роли» в согласовании — HR-должности, поэтому получатели
 * уведомлений и эскалация выбираются должностями.
 */
import { useEffect, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Loader2, ShieldCheck } from 'lucide-react';
import { toast } from 'sonner';

import { signoffApi } from '@/api/signoff';
import { PositionPicker } from '@/components/signoff/PositionPicker';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { reportApiError } from '@/lib/apiError';
import type { ApprovalRoute, RouteFlagsInput } from '@/types/signoff';

interface Flags {
  forbid_self_approval: boolean;
  reject_comment_min: number;
  lazy_resolution: boolean;
  skip_unmatched_groups: boolean;
  no_executor_notify_position_ids: number[];
  escalation_position_id: number | null;
  self_skip_notify_position_ids: number[];
}

const flagsOf = (route: ApprovalRoute): Flags => ({
  forbid_self_approval: route.forbid_self_approval,
  reject_comment_min: route.reject_comment_min,
  lazy_resolution: route.lazy_resolution,
  skip_unmatched_groups: route.skip_unmatched_groups ?? false,
  no_executor_notify_position_ids: route.no_executor_notify_position_ids ?? [],
  escalation_position_id: route.escalation_position_id,
  self_skip_notify_position_ids: route.self_skip_notify_position_ids ?? [],
});

const namesOf = (route: ApprovalRoute): Record<number, string> => {
  const names: Record<number, string> = {};
  for (const row of [
    ...(route.no_executor_notify_positions ?? []),
    ...(route.self_skip_notify_positions ?? []),
    ...(route.escalation_position ? [route.escalation_position] : []),
  ]) names[row.id] = row.title;
  return names;
};

export function RouteFlagsCard({ route }: { route: ApprovalRoute }) {
  const queryClient = useQueryClient();
  const [flags, setFlags] = useState<Flags>(() => flagsOf(route));
  const [error, setError] = useState('');

  // Карточка маршрута перечиталась (сохранение, чужая правка) — форма за ней.
  useEffect(() => setFlags(flagsOf(route)), [route]);

  const save = useMutation({
    mutationFn: (input: RouteFlagsInput) =>
      signoffApi.updateRoute(route.id, input).then((r) => r.data),
    onSuccess: () => {
      toast.success('Правила маршрута сохранены');
      queryClient.invalidateQueries({ queryKey: ['signoff'] });
    },
    onError: (err) => reportApiError(err, 'Не удалось сохранить правила маршрута'),
  });

  const names = namesOf(route);
  const set = (patch: Partial<Flags>) => setFlags((prev) => ({ ...prev, ...patch }));

  const submit = () => {
    const min = Number(flags.reject_comment_min);
    if (!Number.isInteger(min) || min < 0 || min > 500) {
      setError('Длина комментария — целое число от 0 до 500.');
      return;
    }
    setError('');
    save.mutate({ ...flags, reject_comment_min: min });
  };

  return (
    <section className="mb-6 rounded-lg border p-4 space-y-4" aria-labelledby="route-flags-title">
      <div className="flex items-center gap-2">
        <ShieldCheck className="h-5 w-5 text-muted-foreground" />
        <h2 id="route-flags-title" className="text-lg font-semibold">Правила маршрута</h2>
      </div>
      <p className="text-sm text-muted-foreground">
        Действуют для документов, отправленных после сохранения: идущие
        согласования живут по правилам на момент отправки.
      </p>

      <div className="flex items-start justify-between gap-4">
        <div>
          <Label htmlFor="flag-self">Запрет самосогласования</Label>
          <p className="text-xs text-muted-foreground">
            Автор документа не согласует его сам: его шаг получает другой
            держатель должности или временный исполнитель, иначе — должность
            эскалации.
          </p>
        </div>
        <Switch id="flag-self" checked={flags.forbid_self_approval}
          onCheckedChange={(checked) => set({ forbid_self_approval: checked })} />
      </div>

      {flags.forbid_self_approval && (
        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-1.5">
            <Label>Должность эскалации</Label>
            <PositionPicker
              value={flags.escalation_position_id ? [flags.escalation_position_id] : []}
              knownNames={names}
              onChange={(ids) => set({ escalation_position_id: ids.length ? ids[ids.length - 1] : null })}
            />
            <p className="text-xs text-muted-foreground">
              Кому уходит шаг автора, если заменить его некем (генеральный директор).
            </p>
          </div>
          <div className="space-y-1.5">
            <Label>Кого уведомить, если автор — сама эскалация</Label>
            <PositionPicker
              value={flags.self_skip_notify_position_ids}
              knownNames={names}
              onChange={(ids) => set({ self_skip_notify_position_ids: ids })}
            />
            <p className="text-xs text-muted-foreground">
              Шаг пропускается с записью в журнале (финансовый директор).
            </p>
          </div>
        </div>
      )}

      <div className="flex items-start justify-between gap-4">
        <div>
          <Label htmlFor="flag-lazy">Исполнитель — при начале этапа</Label>
          <p className="text-xs text-muted-foreground">
            Кто согласует шаг, решается, когда до него дошла очередь, с учётом
            временных исполнителей. Нет никого — документ ждёт со статусом
            «Нет исполнителя», а не отказывает в отправке.
          </p>
        </div>
        <Switch id="flag-lazy" checked={flags.lazy_resolution}
          onCheckedChange={(checked) => set({ lazy_resolution: checked })} />
      </div>

      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Label htmlFor="flag-skip" className="text-sm">
            Шаг без подходящей ветки пропускается
          </Label>
          <p className="text-xs text-muted-foreground">
            Если ни одно условие шага не сошлось и «иначе» нет, шаг пропускается, а не
            отказывает в отправке. Не осталось ни одного шага — документ согласован
            сразу (например, допсоглашение без изменения суммы).
          </p>
        </div>
        <Switch id="flag-skip" checked={flags.skip_unmatched_groups}
          onCheckedChange={(checked) => set({ skip_unmatched_groups: checked })} />
      </div>

      {flags.lazy_resolution && (
        <div className="space-y-1.5">
          <Label>Кого уведомить о «Нет исполнителя»</Label>
          <PositionPicker
            value={flags.no_executor_notify_position_ids}
            knownNames={names}
            onChange={(ids) => set({ no_executor_notify_position_ids: ids })}
          />
          <p className="text-xs text-muted-foreground">
            Тех, кто может назначить исполнителя (администратор, генеральный директор).
          </p>
        </div>
      )}

      <div className="max-w-xs space-y-1.5">
        <Label htmlFor="flag-comment">Комментарий при отказе и возврате, символов</Label>
        <Input id="flag-comment" type="number" min={0} max={500}
          value={flags.reject_comment_min}
          onChange={(event) => set({ reject_comment_min: Number(event.target.value) })} />
        <p className="text-xs text-muted-foreground">0 — комментарий не обязателен.</p>
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}
      <Button type="button" onClick={submit} disabled={save.isPending}>
        {save.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
        Сохранить правила
      </Button>
    </section>
  );
}
