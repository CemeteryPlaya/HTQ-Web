/**
 * Дерево работ проекта: площадка → блок → роудмап → задача → подзадача.
 *
 * Жило внутри `HRRoadmap.tsx`, пока смотрело на него одно место. Теперь
 * второе — вкладка «Объекты» карточки проекта, где вопрос тот же: что на
 * этом объекте идёт и что к работам приписано. Копия на двести строк с
 * четырьмя уровнями вложенности разошлась бы с оригиналом на первой же
 * правке, поэтому дерево вынесено сюда целиком, вместе с раскладкой.
 *
 * Три корзины, которые НЕ являются ошибкой и потому показываются наравне
 * с остальным:
 *
 * * «без роудмапа» — задачи вне пакетов; так живут все, заведённые до
 *   появления этого уровня;
 * * «без блока» — задача не привязана к участку;
 * * «без объекта» — у исторических задач объекта нет и вывести его неоткуда.
 */
import React, { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  BookOpen, Boxes, Bug, CheckSquare, ChevronDown, ChevronRight, Layers,
  ListTodo, MapPin,
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Collapsible, CollapsibleContent, CollapsibleTrigger,
} from '@/components/ui/collapsible';
import { Progress } from '@/components/ui/progress';
import { roadmapStatusBadgeClass, roadmapStatusLabel } from '@/lib/tasks/roadmap';
import { statusBadgeClass } from '@/lib/tasks/status';
import { buildTaskTree, buildWorkTree } from '@/lib/tasks/workTree';
import type { TaskNode, Translate } from '@/lib/tasks/workTree';
import type { Project, Roadmap, Task } from '@/types/tasks';

const TYPE_ICONS: Record<string, React.ReactNode> = {
  task: <CheckSquare className="h-4 w-4 text-blue-500" />,
  bug: <Bug className="h-4 w-4 text-red-500" />,
  story: <BookOpen className="h-4 w-4 text-green-500" />,
  epic: <Layers className="h-4 w-4 text-purple-500" />,
  subtask: <ListTodo className="h-4 w-4 text-gray-500" />,
};

const TaskRow: React.FC<{
  node: TaskNode;
  depth: number;
  t: Translate;
}> = ({ node, depth, t }) => {
  const { task } = node;
  return (
    <>
      <Link
        to={`/tasks/${task.id}`}
        className="flex items-center gap-3 p-2 rounded-lg hover:bg-muted transition-colors"
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
      >
        {depth > 0 && (
          <span className="text-muted-foreground text-xs">↳</span>
        )}
        {TYPE_ICONS[task.task_type] ?? <CheckSquare className="h-4 w-4 text-muted-foreground" />}
        <span className="font-mono text-sm text-primary">{task.key}</span>
        <span className="text-sm flex-1 truncate">{task.summary}</span>
        <Badge className={statusBadgeClass(task.status)} variant="secondary">
          {t(`tasks.pages.list.status.${task.status}`, task.status)}
        </Badge>
        {task.assignee_name && (
          <span className="text-xs text-muted-foreground">{task.assignee_name}</span>
        )}
      </Link>
      {node.children.map((child) => (
        <TaskRow key={child.task.id} node={child} depth={depth + 1} t={t} />
      ))}
    </>
  );
};

/* ---- Роудмап внутри блока: свои задачи и своя полоса ---- */

const RoadmapRow: React.FC<{
  roadmap: Roadmap;
  tasks: Task[];
  t: Translate;
}> = ({ roadmap, tasks, t }) => {
  const [open, setOpen] = useState(false);
  const tree = useMemo(() => buildTaskTree(tasks), [tasks]);

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <div
        className="rounded-lg border bg-card/40"
        style={{ borderLeftWidth: 3, borderLeftColor: roadmap.color }}
      >
        <CollapsibleTrigger asChild>
          <div className="flex items-center gap-2 p-2 cursor-pointer hover:bg-muted/40 rounded-lg transition-colors">
            {open
              ? <ChevronDown className="h-4 w-4 text-muted-foreground shrink-0" />
              : <ChevronRight className="h-4 w-4 text-muted-foreground shrink-0" />}
            <Layers className="h-4 w-4 shrink-0" style={{ color: roadmap.color }} />
            <span className="text-sm font-medium flex-1 truncate">{roadmap.name}</span>
            <Badge className={roadmapStatusBadgeClass(roadmap.status)} variant="secondary">
              {roadmapStatusLabel(roadmap.status, t)}
            </Badge>
            {roadmap.planned_working_days !== null && (
              <span className="text-xs text-muted-foreground whitespace-nowrap">
                {t('tasks.pages.roadmaps.plan', 'План')}: {roadmap.planned_working_days}{' '}
                {t('tasks.pages.roadmaps.days', 'дн.')}
              </span>
            )}
            <span className="text-xs text-muted-foreground whitespace-nowrap">
              {roadmap.done_count}/{roadmap.task_count}
            </span>
            <div className="w-20 shrink-0">
              <Progress value={roadmap.progress} className="h-1.5" />
            </div>
            <Button
              asChild
              size="sm"
              variant="ghost"
              className="h-7 px-2"
              // stopPropagation: клик по ссылке внутри триггера иначе ещё и
              // схлопывает раскрытый пакет.
              onClick={(event) => event.stopPropagation()}
            >
              <Link to={`/tasks/roadmaps/${roadmap.id}`}>
                {t('tasks.pages.roadmaps.planVsFact', 'План и факт')}
              </Link>
            </Button>
          </div>
        </CollapsibleTrigger>

        <CollapsibleContent>
          <div className="px-2 pb-2 space-y-1">
            {tree.length === 0 ? (
              <p className="text-muted-foreground text-sm py-2 pl-6">
                {t('tasks.pages.roadmaps.noTasks', 'Задач пока нет')}
              </p>
            ) : (
              tree.map((node) => (
                <TaskRow key={node.task.id} node={node} depth={1} t={t} />
              ))
            )}
          </div>
        </CollapsibleContent>
      </div>
    </Collapsible>
  );
};

/* ---- Блок объекта: свои роудмапы плюс задачи вне пакетов ---- */

const BlockGroup: React.FC<{
  name: string;
  roadmaps: Roadmap[];
  tasksByRoadmap: Map<number | null, Task[]>;
  t: Translate;
}> = ({ name, roadmaps, tasksByRoadmap, t }) => {
  // `?? []` внутри useMemo, а не снаружи: снаружи он создавал бы новый
  // массив на каждый рендер и обнулял мемоизацию.
  const looseTree = useMemo(
    () => buildTaskTree(tasksByRoadmap.get(null) ?? []),
    [tasksByRoadmap],
  );

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <Boxes className="h-4 w-4 shrink-0 text-muted-foreground" />
        <span className="text-sm font-medium">{name}</span>
        <span className="text-xs text-muted-foreground">
          {t('tasks.pages.roadmaps.title', 'Роудмапы')}: {roadmaps.length}
        </span>
      </div>

      <div className="pl-6 space-y-2">
        {roadmaps.map((roadmap) => (
          <RoadmapRow
            key={roadmap.id}
            roadmap={roadmap}
            tasks={tasksByRoadmap.get(roadmap.id) ?? []}
            t={t}
          />
        ))}

        {looseTree.length > 0 && (
          <div className="rounded-lg border border-dashed">
            <div className="flex items-center gap-2 p-2 text-xs text-muted-foreground">
              <ListTodo className="h-3.5 w-3.5" />
              {t('tasks.pages.roadmaps.noRoadmap', 'Без роудмапа')}
            </div>
            <div className="px-2 pb-2 space-y-1">
              {looseTree.map((node) => (
                <TaskRow key={node.task.id} node={node} depth={1} t={t} />
              ))}
            </div>
          </div>
        )}

        {roadmaps.length === 0 && looseTree.length === 0 && (
          <p className="text-muted-foreground text-sm py-1">
            {t('tasks.pages.roadmaps.empty', 'Роудмапов пока нет')}
          </p>
        )}
      </div>
    </div>
  );
};

/* ---- Площадка: свои блоки, каждый со своими пакетами ---- */

const SiteGroup: React.FC<{
  name: string;
  color: string;
  /** Пакеты площадки, разложенные по блокам. */
  roadmapsByBlock: Map<number, Roadmap[]>;
  /** Задачи площадки: блок → пакет → задачи. */
  tasksByBlock: Map<number | null, Map<number | null, Task[]>>;
  blockNames: Map<number, string>;
  t: Translate;
  /** Строка справа от названия — счётчики, кнопки, что угодно. */
  aside?: React.ReactNode;
}> = ({ name, color, roadmapsByBlock, tasksByBlock, blockNames, t, aside }) => {
  /**
   * Блоки площадки — объединение тех, где есть пакеты, и тех, где есть
   * только задачи. Плюс корзина `null`: задача без блока законна (её
   * заводили до появления уровня или она не привязана к участку).
   */
  const blockKeys = useMemo(() => {
    const keys = new Set<number | null>(roadmapsByBlock.keys());
    tasksByBlock.forEach((_, key) => keys.add(key));
    return [...keys].sort((a, b) => {
      // Корзина «без блока» всегда последняя — она не участок, а остаток.
      if (a === null) return 1;
      if (b === null) return -1;
      return (blockNames.get(a) ?? '').localeCompare(blockNames.get(b) ?? '');
    });
  }, [roadmapsByBlock, tasksByBlock, blockNames]);

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <MapPin className="h-4 w-4 shrink-0" style={{ color }} />
        <span className="text-sm font-semibold" style={{ color }}>{name}</span>
        {aside}
      </div>

      <div className="pl-6 space-y-3">
        {blockKeys.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            {t('tasks.pages.blocks.empty', 'Блоков пока нет')}
          </p>
        ) : blockKeys.map((key) => (
          <BlockGroup
            key={key ?? 'no-block'}
            name={key === null
              ? t('tasks.pages.blocks.noBlock', 'Без блока')
              : (blockNames.get(key) ?? `#${key}`)}
            roadmaps={key === null ? [] : (roadmapsByBlock.get(key) ?? [])}
            tasksByRoadmap={tasksByBlock.get(key) ?? new Map()}
            t={t}
          />
        ))}
      </div>
    </div>
  );
};

/* ---- Готовое дерево целиком ---- */

/**
 * Все площадки проекта деревом. Пустое состояние остаётся за вызывающим:
 * на странице роудмапа это «в проекте нет задач», во вкладке «Объекты» —
 * приглашение отметить объекты, и общего текста у них нет.
 */
export const SiteWorkTree: React.FC<{
  project: Pick<Project, 'sites'>;
  tasks: Task[];
  roadmaps: Roadmap[];
  t: Translate;
}> = ({ project, tasks, roadmaps, t }) => {
  const tree = useMemo(
    () => buildWorkTree(project, tasks, roadmaps, t),
    [project, tasks, roadmaps, t],
  );

  return (
    <div className="space-y-5">
      {tree.siteRows.map((site) => (
        <SiteGroup
          key={site.key ?? 'no-site'}
          name={site.name}
          color={site.color}
          roadmapsByBlock={site.key === null
            ? new Map()
            : (tree.roadmapsBySite.get(site.key) ?? new Map())}
          tasksByBlock={tree.tasksBySite.get(site.key) ?? new Map()}
          blockNames={tree.blockNames}
          t={t}
        />
      ))}
    </div>
  );
};
