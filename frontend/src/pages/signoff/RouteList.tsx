/**
 * Маршруты согласования — по одному согласуемому типу.
 *
 * Страница строится вокруг РЕЕСТРА ТИПОВ (`GET /subjects`), а не вокруг
 * списка маршрутов: список типов наполняют сами предметные аппки на старте,
 * и «для чего вообще можно завести маршрут» — вопрос к нему. Маршруты
 * подкладываются к типам.
 *
 * **Активный маршрут на тип ровно один** (частичный уникальный индекс), и
 * второй бэкенд отобьёт 409. Поэтому кнопка «Создать» превращается в
 * «Создать неактивным», как только активный уже есть: завести запасной
 * маршрут можно, включить два сразу — нет.
 *
 * **Включение маршрута — поступок.** С этого момента `contracts` перестаёт
 * принимать несогласованную бюджетную строку как источник денег и
 * несогласованного контрагента как сторону договора. Без активного
 * маршрута не блокируется ничего.
 */

import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, GitBranch, Loader2, Plus } from 'lucide-react';
import { toast } from 'sonner';

import { SignoffShell } from '@/components/signoff/SignoffShell';
import { reportApiError } from '@/components/signoff/apiError';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { signoffApi } from '@/api/signoff';
import type { ApprovalRoute, Subject } from '@/types/signoff';

const RouteList = () => {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [creatingFor, setCreatingFor] = useState<Subject | null>(null);
  const [name, setName] = useState('');

  const {
    data: subjects = [],
    isLoading: subjectsLoading,
    isError: subjectsError,
  } = useQuery({
    queryKey: ['signoff', 'subjects'],
    queryFn: () => signoffApi.listSubjects().then((r) => r.data),
  });

  const { data: routes = [], isLoading: routesLoading } = useQuery({
    queryKey: ['signoff', 'routes'],
    queryFn: () => signoffApi.listRoutes().then((r) => r.data),
  });

  const routesByType = useMemo(() => {
    const map = new Map<string, ApprovalRoute[]>();
    for (const route of routes) {
      const bucket = map.get(route.subject_type);
      if (bucket) bucket.push(route);
      else map.set(route.subject_type, [route]);
    }
    return map;
  }, [routes]);

  /** Маршруты на типы, которых больше нет в реестре: аппку отключили или
   *  сняли регистрацию. Строки в БД остались, и прятать их нельзя. */
  const orphanTypes = useMemo(() => {
    const known = new Set(subjects.map((subject) => subject.subject_type));
    return [...routesByType.keys()].filter((type) => !known.has(type));
  }, [routesByType, subjects]);

  const create = useMutation({
    mutationFn: ({ subjectType, isActive }: { subjectType: string; isActive: boolean }) =>
      signoffApi
        .createRoute({ subject_type: subjectType, name, is_active: isActive })
        .then((r) => r.data),
    onSuccess: (route) => {
      toast.success('Маршрут создан — добавьте этапы');
      setCreatingFor(null);
      setName('');
      queryClient.invalidateQueries({ queryKey: ['signoff'] });
      // Маршрут без этапов неисполним, так что новый ведёт сразу в редактор:
      // «создал и забыл» здесь означает тип, который нельзя согласовать.
      navigate(`/signoff/routes/${route.id}`);
    },
    // 409 — тип не зарегистрирован либо активный маршрут для него уже есть.
    onError: (err) => reportApiError(err, 'Не удалось создать маршрут'),
  });

  const openCreate = (subject: Subject) => {
    setCreatingFor(subject);
    setName(`Согласование: ${subject.label.toLowerCase()}`);
  };

  const isLoading = subjectsLoading || routesLoading;

  return (
    <SignoffShell>
      <div className="mb-6 flex items-center gap-3">
        <GitBranch className="h-7 w-7 text-muted-foreground" />
        <div>
          <h1 className="text-3xl font-bold">Маршруты</h1>
          <p className="text-sm text-muted-foreground">
            Кто и в каком порядке согласует объекты каждого типа.
          </p>
        </div>
      </div>

      <Alert className="mb-6">
        <AlertTriangle className="h-4 w-4" />
        <AlertDescription>
          Включённый маршрут меняет поведение предметной аппки: с этого
          момента несогласованный объект перестаёт приниматься там, где его
          согласование проверяется (у договоров — бюджетная строка и
          контрагент). Пока активного маршрута для типа нет, не блокируется
          ничего.
        </AlertDescription>
      </Alert>

      {isLoading ? (
        <div className="space-y-3">
          {[0, 1, 2].map((row) => (
            <Skeleton key={row} className="h-28 w-full" />
          ))}
        </div>
      ) : subjectsError ? (
        <p className="text-sm text-destructive">
          Не удалось загрузить список согласуемых типов.
        </p>
      ) : subjects.length === 0 ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Согласуемых типов нет</CardTitle>
            <CardDescription>
              Реестр наполняют сами предметные аппки при старте бэкенда. Пустой
              список значит, что ни одна из них себя не зарегистрировала —
              либо все они отключены.
            </CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <div className="space-y-4">
          {subjects.map((subject) => {
            const typeRoutes = routesByType.get(subject.subject_type) ?? [];
            return (
              <Card key={subject.subject_type}>
                <CardHeader className="pb-3">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <CardTitle className="text-base flex items-center gap-2">
                        {subject.label}
                        {subject.has_active_route ? (
                          <Badge
                            variant="outline"
                            className="border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
                          >
                            согласование включено
                          </Badge>
                        ) : (
                          <Badge variant="outline" className="text-muted-foreground">
                            без активного маршрута
                          </Badge>
                        )}
                      </CardTitle>
                      <CardDescription className="font-mono text-xs mt-1">
                        {subject.subject_type}
                      </CardDescription>
                    </div>
                    <Button
                      size="sm"
                      variant={subject.has_active_route ? 'outline' : 'default'}
                      onClick={() => openCreate(subject)}
                    >
                      <Plus className="mr-1.5 h-4 w-4" />
                      {subject.has_active_route
                        ? 'Ещё маршрут (неактивный)'
                        : 'Создать маршрут'}
                    </Button>
                  </div>
                </CardHeader>
                <CardContent>
                  {typeRoutes.length === 0 ? (
                    <p className="text-sm text-muted-foreground">
                      Маршрутов нет — объекты этого типа отправить на
                      согласование нельзя.
                    </p>
                  ) : (
                    <ul className="divide-y">
                      {typeRoutes.map((route) => (
                        <li
                          key={route.id}
                          className="flex flex-wrap items-center justify-between gap-2 py-2 first:pt-0 last:pb-0"
                        >
                          <div className="min-w-0">
                            <Link
                              to={`/signoff/routes/${route.id}`}
                              className="font-medium hover:underline underline-offset-2"
                            >
                              {route.name}
                            </Link>
                            <p className="text-xs text-muted-foreground">
                              {route.stages.length === 0
                                ? 'этапов нет — маршрут неисполним'
                                : `этапов: ${route.stages.length}`}
                            </p>
                          </div>
                          <Badge variant={route.is_active ? 'default' : 'outline'}>
                            {route.is_active ? 'активен' : 'выключен'}
                          </Badge>
                        </li>
                      ))}
                    </ul>
                  )}
                </CardContent>
              </Card>
            );
          })}

          {orphanTypes.length > 0 && (
            <Card className="border-dashed">
              <CardHeader className="pb-3">
                <CardTitle className="text-base">
                  Маршруты на незарегистрированные типы
                </CardTitle>
                <CardDescription>
                  Эти типы больше не приходят из реестра — их аппка отключена
                  или сняла регистрацию. Маршруты остались в базе и здесь
                  показаны, чтобы о них было известно.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <ul className="divide-y">
                  {orphanTypes.flatMap((type) =>
                    (routesByType.get(type) ?? []).map((route) => (
                      <li key={route.id} className="py-2 first:pt-0 last:pb-0">
                        <Link
                          to={`/signoff/routes/${route.id}`}
                          className="font-medium hover:underline underline-offset-2"
                        >
                          {route.name}
                        </Link>
                        <span className="ml-2 font-mono text-xs text-muted-foreground">
                          {type}
                        </span>
                      </li>
                    )),
                  )}
                </ul>
              </CardContent>
            </Card>
          )}
        </div>
      )}

      <Dialog
        open={creatingFor !== null}
        onOpenChange={(open) => !open && setCreatingFor(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Новый маршрут</DialogTitle>
            <DialogDescription>
              {creatingFor?.label}
              {creatingFor?.has_active_route && (
                <span className="block mt-2">
                  Активный маршрут для этого типа уже есть, а больше одного
                  быть не может — новый создастся выключенным. Включить его
                  можно, выключив прежний.
                </span>
              )}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-2">
            <Label htmlFor="route-name">Название</Label>
            <Input
              id="route-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              maxLength={200}
              placeholder="Например: согласование бюджетных заявок"
            />
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setCreatingFor(null)}>
              Отмена
            </Button>
            <Button
              disabled={!name.trim() || create.isPending}
              onClick={() =>
                creatingFor
                && create.mutate({
                  subjectType: creatingFor.subject_type,
                  isActive: !creatingFor.has_active_route,
                })
              }
            >
              {create.isPending && (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              )}
              Создать
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </SignoffShell>
  );
};

export default RouteList;
