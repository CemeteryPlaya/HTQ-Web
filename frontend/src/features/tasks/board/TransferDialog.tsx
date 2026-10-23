/**
 * «Отправить в отдел» — перенос задачи в другой отдел (канбан K1.7, мастер-план K-08).
 *
 * Первая версия: этап 5 переиспользует её на доске. Переносит глава отдела
 * задачи или администратор — кнопку показывает флаг сервера `can.transfer`,
 * а не этот компонент. У получателя задача начинается заново: исполнители
 * снимаются, статус — «К выполнению»; отдел-отправитель остаётся при задаче
 * и видит ход работ.
 *
 * Список целей — справочник отделов без текущего отдела задачи и без
 * неактивных: в оба сервер не переносит. Отдел-отправитель спрашивается
 * только у задачи без отдела — у неё сервер иначе возьмёт первый из отделов
 * главы; чужой отдел-отправитель он отвергнет (`task_transfer_sender`).
 */
import React, { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Check } from 'lucide-react';

import { fetchDepartments } from '@/api/hr';
import { transferTask } from '@/api/tasks';
import { Button } from '@/components/ui/button';
import {
  Command, CommandEmpty, CommandInput, CommandItem, CommandList,
} from '@/components/ui/command';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { cn } from '@/lib/utils';
import type { Task } from '@/types/tasks';

import { taskErrorText } from '../errors';

const AUTO_SENDER = 'auto';

interface Props {
  task: Pick<Task, 'id' | 'key' | 'department'>;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onTransferred?: (task: Task) => void;
}

export const TransferDialog: React.FC<Props> = ({ task, open, onOpenChange, onTransferred }) => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [target, setTarget] = useState<number | null>(null);
  const [sender, setSender] = useState<string>(AUTO_SENDER);
  const [error, setError] = useState<string | null>(null);

  const { data: departments = [], isFetched } = useQuery({
    queryKey: ['hr-departments'],
    queryFn: fetchDepartments,
    enabled: open,
  });

  const active = useMemo(
    () => departments.filter((d) => d.is_active !== false),
    [departments],
  );
  const targets = useMemo(
    () => active.filter((d) => d.id !== task.department),
    [active, task.department],
  );

  const reset = () => {
    setTarget(null);
    setSender(AUTO_SENDER);
    setError(null);
  };

  const close = (next: boolean) => {
    if (!next) reset();
    onOpenChange(next);
  };

  const mutation = useMutation({
    mutationFn: () => transferTask(task.id, {
      department_id: target as number,
      ...(sender !== AUTO_SENDER ? { sender_department_id: Number(sender) } : {}),
    }),
    onSuccess: (updated) => {
      queryClient.invalidateQueries({ queryKey: ['hr-task', task.id] });
      queryClient.invalidateQueries({ queryKey: ['employee-task', task.id] });
      queryClient.invalidateQueries({ queryKey: ['hr-tasks'] });
      queryClient.invalidateQueries({ queryKey: ['employee-tasks'] });
      toast.success(t('tasks.transfer.success', 'Задача отправлена в отдел'));
      onTransferred?.(updated);
      close(false);
    },
    onError: (err) => setError(taskErrorText(err, t, t('tasks.transfer.error', 'Не удалось отправить задачу'))),
  });

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t('tasks.transfer.title', 'Отправить в отдел')}</DialogTitle>
          <DialogDescription>
            {t('tasks.transfer.hint', 'Исполнители будут сняты, задача встанет в «К выполнению». Ваш отдел продолжит видеть ход работ.')}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label>{t('tasks.transfer.target', 'Отдел-получатель')}</Label>
            <Command className="rounded-md border">
              <CommandInput placeholder={t('tasks.transfer.search', 'Найти отдел')} />
              <CommandList className="max-h-56">
                <CommandEmpty>{t('tasks.transfer.empty', 'Отделы не найдены')}</CommandEmpty>
                {targets.map((d) => (
                  <CommandItem
                    key={d.id}
                    value={`${d.name} ${d.id}`}
                    onSelect={() => { setTarget(d.id); setError(null); }}
                  >
                    <Check className={cn('mr-2 h-4 w-4', target === d.id ? 'opacity-100' : 'opacity-0')} />
                    {d.name}
                  </CommandItem>
                ))}
              </CommandList>
            </Command>
            {isFetched && targets.length === 0 && (
              <p className="text-xs text-muted-foreground">
                {t('tasks.transfer.noTargets',
                  'Отправить некуда: других действующих отделов в компании нет.')}
              </p>
            )}
          </div>

          {task.department == null && (
            <div className="space-y-1.5">
              <Label>{t('tasks.transfer.sender', 'Отдел-отправитель')}</Label>
              <Select value={sender} onValueChange={setSender}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value={AUTO_SENDER}>
                    {t('tasks.transfer.senderAuto', 'Мой отдел (автоматически)')}
                  </SelectItem>
                  {active.map((d) => (
                    <SelectItem key={d.id} value={String(d.id)}>{d.name}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          {error && (
            <p role="alert" className="text-sm text-destructive">{error}</p>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => close(false)}>
            {t('common.cancel', 'Отмена')}
          </Button>
          <Button
            onClick={() => mutation.mutate()}
            disabled={target === null || mutation.isPending}
          >
            {t('tasks.transfer.submit', 'Отправить')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
