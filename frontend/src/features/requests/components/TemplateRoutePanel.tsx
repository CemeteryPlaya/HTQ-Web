/**
 * Шаг «Маршрут» конструктора шаблона.
 *
 * Согласование заявок ведёт `apps.signoff` — тот же движок, что согласует
 * договоры. Маршрут заявки живёт не в версии формы, а в signoff, в ОБЛАСТИ
 * шаблона (`scope = template:<id>`): у отпуска и у закупа маршруты разные,
 * хотя тип объекта один. Отсюда две вещи, заметные в интерфейсе:
 *
 * * маршрут правится отдельно от формы и **не требует публикации версии** —
 *   он применится к следующей отправке, а идущие согласования работают по
 *   снимку, сделанному при запуске;
 * * редактор здесь — тот же самый `RouteEditorPanel`, что и на странице
 *   `/signoff/routes/:id`. Второй копии редактора не существует.
 *
 * Маршрут создаётся по кнопке, а не молча при открытии шага: пустой маршрут
 * без этапов неисполним, и заводить его за администратора, который просто
 * листал вкладки, значило бы наплодить «маршрутов-пустышек», из-за которых
 * отправка падала бы не с «маршрут не настроен», а с «в маршруте нет этапов».
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { GitBranch, Loader2 } from 'lucide-react';
import { toast } from 'sonner';

import { signoffApi } from '@/api/signoff';
import { RouteEditorPanel } from '@/components/signoff/RouteEditorPanel';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { reportApiError } from '@/lib/apiError';
import { REQUEST_SUBJECT_TYPE, templateScope } from '@/features/requests/subject';

interface Props {
  templateId: number;
  templateName: string;
}

export function TemplateRoutePanel({ templateId, templateName }: Props) {
  const queryClient = useQueryClient();
  const scope = templateScope(templateId);

  const routes = useQuery({
    queryKey: ['signoff', 'routes', scope],
    queryFn: () => signoffApi
      .listRoutes({ subject_type: REQUEST_SUBJECT_TYPE, scope })
      .then((r) => r.data),
  });
  const route = (routes.data ?? [])[0] ?? null;

  const create = useMutation({
    mutationFn: () => signoffApi.createRoute({
      subject_type: REQUEST_SUBJECT_TYPE,
      scope,
      name: `Маршрут «${templateName}»`,
    }).then((r) => r.data),
    onSuccess: () => {
      toast.success('Маршрут создан — добавьте этапы');
      queryClient.invalidateQueries({ queryKey: ['signoff'] });
    },
    onError: (err) => reportApiError(err, 'Не удалось создать маршрут'),
  });

  if (routes.isLoading) return <Skeleton className="h-64" />;
  if (routes.isError) {
    return (
      <p className="text-sm text-destructive">
        Не удалось загрузить маршрут: раздел согласований недоступен.
      </p>
    );
  }

  if (!route) {
    return (
      <div className="rounded-lg border border-dashed p-10 text-center">
        <GitBranch className="mx-auto mb-3 h-8 w-8 text-muted-foreground" />
        <p className="mb-1 font-medium">Маршрут согласования не настроен</p>
        <p className="mx-auto mb-4 max-w-prose text-sm text-muted-foreground">
          Пока маршрута нет, отправить заявку по этому шаблону нельзя — отправка
          ответит «не настроен маршрут согласования». Маршрут задаётся один раз
          и правится независимо от формы: публиковать версию ради него не нужно.
        </p>
        <Button onClick={() => create.mutate()} disabled={create.isPending}>
          {create.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
          Создать маршрут
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Маршрут этого шаблона. Правки применяются к следующим отправкам —
        заявки, уже ушедшие на согласование, идут по снимку маршрута, сделанному
        при запуске.
      </p>
      <RouteEditorPanel routeId={route.id} />
    </div>
  );
}
