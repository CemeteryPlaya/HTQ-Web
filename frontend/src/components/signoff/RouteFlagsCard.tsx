/**
 * «Правила маршрута» — флаги маршрута согласования (мастер-план БЗО, D-21).
 *
 * Все выключены по умолчанию: маршрут без них работает как раньше. Флаги
 * снимком уходят в процесс при отправке — правка здесь не меняет уже идущие
 * согласования. «Роли» в согласовании — HR-должности, поэтому получатели
 * уведомлений и эскалация выбираются должностями — своей компании или
 * вышестоящей (B8.1: ГД и ФД дочерней — в штате холдинга).
 *
 * Исключение из «снимком при отправке» — «Решение из вышестоящей компании»:
 * его движок читает из маршрута в момент решения, поэтому оно действует
 * сразу, в том числе на идущие согласования.
 */
import { useEffect, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Loader2, ShieldCheck } from 'lucide-react';
import { toast } from 'sonner';

import { signoffApi } from '@/api/signoff';
import { PositionPicker } from '@/components/signoff/PositionPicker';
import { refKey } from '@/components/signoff/crossCompany';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { reportApiError } from '@/lib/apiError';
import type { ApprovalRoute, PositionBrief, PositionRef, RouteFlagsInput } from '@/types/signoff';

interface Flags {
  forbid_self_approval: boolean;
  reject_comment_min: number;
  lazy_resolution: boolean;
  skip_unmatched_groups: boolean;
  /** Должности парами: свои и вышестоящих компаний вместе (B8.1). */
  no_executor_notify: PositionRef[];
  escalation: PositionRef | null;
  self_skip_notify: PositionRef[];
  allow_direct_decisions: boolean;
}

const own = (ids: number[] | undefined): PositionRef[] =>
  (ids ?? []).map((id) => ({ company: '', position_id: id }));

const flagsOf = (route: ApprovalRoute): Flags => ({
  forbid_self_approval: route.forbid_self_approval,
  reject_comment_min: route.reject_comment_min,
  lazy_resolution: route.lazy_resolution,
  skip_unmatched_groups: route.skip_unmatched_groups ?? false,
  no_executor_notify: [...own(route.no_executor_notify_position_ids),
    ...(route.no_executor_notify_foreign ?? [])],
  escalation: route.escalation_position_id
    ? { company: route.escalation_position_company ?? '', position_id: route.escalation_position_id }
    : null,
  self_skip_notify: [...own(route.self_skip_notify_position_ids),
    ...(route.self_skip_notify_foreign ?? [])],
  allow_direct_decisions: route.allow_direct_decisions ?? false,
});

/** Пары обратно в поля ручки: свои — id, вышестоящих компаний — парами. */
const split = (refs: PositionRef[]) => ({
  own: refs.filter((ref) => !ref.company).map((ref) => ref.position_id),
  foreign: refs.filter((ref) => ref.company),
});

const namesOf = (route: ApprovalRoute): Record<string, string> => {
  const names: Record<string, string> = {};
  const rows: PositionBrief[] = [
    ...(route.no_executor_notify_positions ?? []),
    ...(route.self_skip_notify_positions ?? []),
    ...(route.escalation_position ? [route.escalation_position] : []),
  ];
  for (const row of rows) names[refKey({ company: row.company ?? '', position_id: row.id })] = row.title;
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
    const notify = split(flags.no_executor_notify);
    const skip = split(flags.self_skip_notify);
    save.mutate({
      forbid_self_approval: flags.forbid_self_approval,
      reject_comment_min: min,
      lazy_resolution: flags.lazy_resolution,
      skip_unmatched_groups: flags.skip_unmatched_groups,
      no_executor_notify_position_ids: notify.own,
      no_executor_notify_foreign: notify.foreign,
      escalation_position_id: flags.escalation?.position_id ?? null,
      escalation_position_company: flags.escalation?.company ?? '',
      self_skip_notify_position_ids: skip.own,
      self_skip_notify_foreign: skip.foreign,
      ...(route.cross_company_decisions
        ? { allow_direct_decisions: flags.allow_direct_decisions } : {}),
    });
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
              single
              value={flags.escalation ? [flags.escalation] : []}
              knownNames={names}
              onChange={(refs) => set({ escalation: refs.length ? refs[refs.length - 1] : null })}
            />
            <p className="text-xs text-muted-foreground">
              Кому уходит шаг автора, если заменить его некем (генеральный директор).
            </p>
          </div>
          <div className="space-y-1.5">
            <Label>Кого уведомить, если автор — сама эскалация</Label>
            <PositionPicker
              value={flags.self_skip_notify}
              knownNames={names}
              onChange={(refs) => set({ self_skip_notify: refs })}
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
            value={flags.no_executor_notify}
            knownNames={names}
            onChange={(refs) => set({ no_executor_notify: refs })}
          />
          <p className="text-xs text-muted-foreground">
            Тех, кто может назначить исполнителя (администратор, генеральный директор).
          </p>
        </div>
      )}

      {route.cross_company_decisions && (
        <div className="flex items-start justify-between gap-4">
          <div>
            <Label htmlFor="flag-direct">Решение из вышестоящей компании</Label>
            <p className="text-xs text-muted-foreground">
              Согласующий из холдинга решает задачу прямо из своей очереди, не
              переходя на адрес этой компании. Этап с документом согласующего или
              выбором варианта всё равно откроется здесь. Действует сразу, в том
              числе на идущие согласования.
            </p>
          </div>
          <Switch id="flag-direct" checked={flags.allow_direct_decisions}
            onCheckedChange={(checked) => set({ allow_direct_decisions: checked })} />
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
