/**
 * Список согласований — надзорный экран.
 *
 * Страница доступна всем, но API возвращает обычному сотруднику только те
 * процессы, которые он отправил либо в которых назначен согласующим.
 * Администратор видит все процессы для надзора.
 *
 * Отсюда фильтр «Мои» — это `initiator_id` = текущий пользователь, то есть
 * «что отправил я». Без фильтра список включает также процессы, где
 * пользователь был или остаётся согласующим.
 */

import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ListChecks } from 'lucide-react';

import { SignoffShell } from '@/components/signoff/SignoffShell';
import { SubjectLink } from '@/components/signoff/SubjectLink';
import { formatMoment } from '@/components/signoff/format';
import { ProcessStateBadge } from '@/components/signoff/states';
import { labelMap } from '@/components/signoff/labels';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { signoffApi, type ProcessListParams } from '@/api/signoff';
import { useActiveProfile } from '@/hooks/useActiveProfile';

/** Значение «фильтр не выбран» для shadcn-select: пустая строка ему
 *  запрещена (Radix трактует её как «сбросить значение»). */
const ANY = '__any__';

const ProcessList = () => {
  const { activeProfile } = useActiveProfile();
  const myId = activeProfile?.id ? Number(activeProfile.id) : null;

  const [subjectType, setSubjectType] = useState(ANY);
  const [state, setState] = useState(ANY);
  const [mineOnly, setMineOnly] = useState(false);

  const { data: subjects = [] } = useQuery({
    queryKey: ['signoff', 'subjects'],
    queryFn: () => signoffApi.listSubjects().then((r) => r.data),
  });
  const { data: enums } = useQuery({
    queryKey: ['signoff', 'enums'],
    queryFn: () => signoffApi.getEnums().then((r) => r.data),
  });

  const params: ProcessListParams = useMemo(() => {
    const next: ProcessListParams = {};
    if (subjectType !== ANY) next.subject_type = subjectType;
    if (state !== ANY) next.state = state;
    if (mineOnly && myId !== null) next.initiator_id = myId;
    return next;
  }, [subjectType, state, mineOnly, myId]);

  const {
    data: processes = [],
    isLoading,
    isError,
  } = useQuery({
    queryKey: ['signoff', 'processes', params],
    queryFn: () => signoffApi.listProcesses(params).then((r) => r.data),
  });

  const subjectLabels = useMemo(
    () => Object.fromEntries(subjects.map((s) => [s.subject_type, s.label])),
    [subjects],
  );
  const processStateLabels = useMemo(
    () => labelMap(enums?.process_state),
    [enums],
  );

  return (
    <SignoffShell>
      <div className="mb-6 flex items-center gap-3">
        <ListChecks className="h-7 w-7 text-muted-foreground" />
        <div>
          <h1 className="text-3xl font-bold">Согласования</h1>
          <p className="text-sm text-muted-foreground">
            Все запущенные процессы — идущие и завершённые.
          </p>
        </div>
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Select value={subjectType} onValueChange={setSubjectType}>
          <SelectTrigger className="w-56">
            <SelectValue placeholder="Тип объекта" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ANY}>Все типы объектов</SelectItem>
            {subjects.map((subject) => (
              <SelectItem key={subject.subject_type} value={subject.subject_type}>
                {subject.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={state} onValueChange={setState}>
          <SelectTrigger className="w-52">
            <SelectValue placeholder="Состояние" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ANY}>Любое состояние</SelectItem>
            {(enums?.process_state ?? []).map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Button
          variant={mineOnly ? 'default' : 'outline'}
          onClick={() => setMineOnly((value) => !value)}
          disabled={myId === null}
          title={
            myId === null
              ? 'Профиль ещё не загружен'
              : 'Только то, что отправил я'
          }
        >
          Мои отправленные
        </Button>
      </div>

      <div className="bg-card rounded-lg border overflow-x-auto">
        {isLoading ? (
          <div className="p-6 space-y-3">
            {[0, 1, 2].map((row) => (
              <Skeleton key={row} className="h-10 w-full" />
            ))}
          </div>
        ) : isError ? (
          <p className="p-6 text-sm text-destructive">
            Не удалось загрузить согласования.
          </p>
        ) : processes.length === 0 ? (
          <p className="p-10 text-center text-muted-foreground">
            Ни одного согласования по этим условиям.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-16">#</TableHead>
                <TableHead>Объект</TableHead>
                <TableHead>Тип</TableHead>
                <TableHead>Состояние</TableHead>
                <TableHead>Запущено</TableHead>
                <TableHead>Завершено</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {processes.map((process) => (
                <TableRow key={process.id}>
                  <TableCell>
                    <Link
                      to={`/signoff/processes/${process.id}`}
                      className="font-medium hover:underline underline-offset-2"
                    >
                      {process.id}
                    </Link>
                  </TableCell>
                  <TableCell>
                    <SubjectLink
                      title={process.subject_title}
                      url={process.subject_url}
                      subjectType={process.subject_type}
                      subjectId={process.subject_id}
                    />
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {subjectLabels[process.subject_type] ?? process.subject_type}
                  </TableCell>
                  <TableCell>
                    <ProcessStateBadge
                      state={process.state}
                      label={processStateLabels[process.state]}
                    />
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground whitespace-nowrap">
                    {formatMoment(process.created_at)}
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground whitespace-nowrap">
                    {formatMoment(process.finished_at) || '—'}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>
    </SignoffShell>
  );
};

export default ProcessList;
