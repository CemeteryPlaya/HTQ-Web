/**
 * Проект из модуля задач в договорной карточке.
 *
 * Один компонент на все места (бюджет, договор, справочник администраторов),
 * потому что различать здесь нечего, а вот три копии разъехались бы при первой
 * же правке — как разъехалось само название проекта до появления связи.
 *
 * Три состояния, и путать их нельзя:
 *
 * * связь есть — бейдж-ссылка на доску задач;
 * * связи нет (`projectId` пустой) — не рисуем ничего: договорный контур
 *   ведут и по проектам, которых на доске нет вовсе;
 * * связь есть, а проекта нет — приглушённая подпись «проект удалён».
 *   Молча показать «не связан» было бы враньём: id в базе остался, и
 *   восстановить связь можно только зная, что она была.
 *
 * Ссылкой бейдж становится ТОЛЬКО для тех, кого пустит сам маршрут:
 * единственная страница проекта — `/tasks/projects/:id/plan-fact`, и она
 * закрыта требованием `{ module: 'hr', level: 'read' }`. Договорами
 * занимаются не только кадры, и ссылка, ведущая в отказ, хуже её отсутствия —
 * остальные видят тот же бейдж без перехода. Условие берётся из того же
 * `usePermissions`, что и охрана маршрута (`routeDefinitions.ts`), а не из
 * своей копии: прежняя копия уже успела разъехаться с оригиналом и прятала
 * ссылку от администратора.
 */
import { Link } from 'react-router-dom';
import { FolderKanban } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { usePermissions } from '@/hooks/usePermissions';
import { cn } from '@/lib/utils';

export interface ProjectLinkBadgeProps {
  projectId: number | null | undefined;
  /** Подпись. В бюджете и договоре это `administrator_name`, который бэкенд
   *  держит синхронным с названием проекта. */
  name?: string | null;
  /** Цвет проекта с доски задач, если он известен (справочник администраторов
   *  отдаёт паспорт целиком, карточки — только id). */
  color?: string | null;
  /** Известно ли, что проект ещё существует. `false` — связь висит на
   *  удалённом проекте. `undefined` — не проверяли (карточки не ходят в
   *  задачи ради этого, см. project_id в serialize_budget). */
  exists?: boolean;
  className?: string;
}

const ProjectLinkBadge = ({
  projectId,
  name,
  color,
  exists,
  className,
}: ProjectLinkBadgeProps) => {
  const permissions = usePermissions();
  // Тот же гейт, что охраняет сам маршрут, — не своя копия правил.
  const canOpen = permissions.atLeast('hr', 'read');

  if (!projectId) return null;

  if (exists === false) {
    return (
      <Badge
        variant="outline"
        className={cn('gap-1.5 text-muted-foreground', className)}
        title="Связь указывает на проект, которого больше нет в модуле задач"
      >
        <FolderKanban className="h-3.5 w-3.5" />
        Проект удалён
      </Badge>
    );
  }

  const inner = (
    <>
      {color ? (
        <span
          aria-hidden
          className="h-2 w-2 shrink-0 rounded-full"
          style={{ backgroundColor: color }}
        />
      ) : (
        <FolderKanban className="h-3.5 w-3.5" />
      )}
      <span className="truncate">{name || `Проект #${projectId}`}</span>
    </>
  );

  if (!canOpen) {
    return (
      <Badge variant="outline" className={cn('gap-1.5', className)}>
        {inner}
      </Badge>
    );
  }

  // Ссылка ОБОРАЧИВАЕТ бейдж, а не наоборот: shadcn-овский Badge — это
  // обычный div без `asChild`, подменить его тег нечем.
  return (
    <Link
      to={`/tasks/projects/${projectId}/plan-fact`}
      title="Открыть проект в задачах"
      className="inline-flex max-w-full"
    >
      <Badge
        variant="outline"
        className={cn('gap-1.5 hover:bg-accent', className)}
      >
        {inner}
      </Badge>
    </Link>
  );
};

export default ProjectLinkBadge;
