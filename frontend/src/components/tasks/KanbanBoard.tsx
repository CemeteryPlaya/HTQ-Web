/**
 * KanbanBoard — Jira + SharePoint quick-edit board.
 *
 * The board renders the 7-status workflow as drag-and-drop columns
 * (status changes happen on drop, just like before), but each card now
 * exposes a popover-based quick-edit surface so users rarely need to
 * navigate to the /tasks/{id} detail page:
 *
 * - Priority chip   → popover with the 5 priorities
 * - Assignee avatars→ popover with primary + collaborator picker
 * - Supervisor chip → popover with single-user picker
 * - Progress bar    → popover with a slider
 * - Labels row      → popover with checkbox list
 *
 * Each control is optimistic: it mutates the local cache copy of the
 * task while the server confirms, so the UX feels instant. On error the
 * TanStack Query invalidation in the parent page restores the truth.
 */
import React, { useState, useEffect, useMemo } from 'react';
import { DragDropContext, Droppable, Draggable, DropResult } from '@hello-pangea/dnd';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
    Bug, BookOpen, Layers, CheckSquare, ListTodo,
    UserPlus, Shield, Tag, ChevronLeft, ChevronRight,
} from 'lucide-react';
import { toast } from 'sonner';

import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Slider } from '@/components/ui/slider';
import { Checkbox } from '@/components/ui/checkbox';
import { Button } from '@/components/ui/button';

import type {
    Task, TaskStatus, TaskPriority, AssigneeRole, Label as LabelType,
} from '@/types/tasks';
import {
    updateTask, updateTaskAssignees, updateTaskSupervisor,
    updateTaskProgress, fetchLabels,
} from '@/api/tasks';
import { fetchEmployeeUsers } from '@/api/hr';

/* ---- Visual config ---- */

const STATUS_ORDER: TaskStatus[] = [
    'backlog', 'todo', 'in_progress', 'in_review', 'blocked', 'done', 'cancelled',
];

const STATUS_TINT: Record<TaskStatus, string> = {
    backlog: 'bg-slate-100 dark:bg-slate-900/40 border-slate-300/40',
    todo: 'bg-slate-100 dark:bg-slate-900/40 border-slate-300/40',
    in_progress: 'bg-blue-50 dark:bg-blue-950/30 border-blue-300/40',
    in_review: 'bg-purple-50 dark:bg-purple-950/30 border-purple-300/40',
    blocked: 'bg-red-50 dark:bg-red-950/30 border-red-300/40',
    done: 'bg-green-50 dark:bg-green-950/30 border-green-300/40',
    cancelled: 'bg-gray-100 dark:bg-gray-900/40 border-gray-300/40',
};

const PRIORITY_COLORS: Record<TaskPriority, string> = {
    critical: 'bg-red-500 text-white',
    high: 'bg-orange-500 text-white',
    medium: 'bg-yellow-500 text-black',
    low: 'bg-blue-500 text-white',
    trivial: 'bg-gray-400 text-white',
};

const PRIORITIES: TaskPriority[] = ['critical', 'high', 'medium', 'low', 'trivial'];

const TYPE_ICONS: Record<string, React.ReactNode> = {
    task: <CheckSquare className="h-4 w-4 text-blue-500 shrink-0" />,
    bug: <Bug className="h-4 w-4 text-red-500 shrink-0" />,
    story: <BookOpen className="h-4 w-4 text-green-500 shrink-0" />,
    epic: <Layers className="h-4 w-4 text-purple-500 shrink-0" />,
    subtask: <ListTodo className="h-4 w-4 text-gray-500 shrink-0" />,
};

interface KanbanBoardProps {
    tasks: Task[];
    onStatusChange: (taskId: number, newStatus: TaskStatus) => void;
}

function initials(name?: string | null): string {
    if (!name) return '?';
    const parts = name.trim().split(/\s+/).slice(0, 2);
    return parts.map(p => p[0]?.toUpperCase() ?? '').join('') || '?';
}

function displayName(u: any): string {
    return u?.full_name || u?.username || `User #${u?.id ?? '?'}`;
}

// How many cards a column shows per page before paginating. Keeps all
// 7 columns visible across the page width without a tall scroll.
const CARDS_PER_PAGE = 6;

export const KanbanBoard: React.FC<KanbanBoardProps> = ({ tasks, onStatusChange }) => {
    const { t } = useTranslation();
    const queryClient = useQueryClient();

    // Local column state mirrors the prop so the UI can reflect a drop
    // immediately, even before the server round-trip completes.
    const [columns, setColumns] = useState<Record<TaskStatus, Task[]>>(
        () => buildColumns(tasks),
    );

    // Per-column pagination — index of the visible page within each column.
    const [pages, setPages] = useState<Record<TaskStatus, number>>(() =>
        STATUS_ORDER.reduce((acc, s) => ({ ...acc, [s]: 0 }), {} as Record<TaskStatus, number>),
    );

    useEffect(() => {
        setColumns(buildColumns(tasks));
    }, [tasks]);

    // Helpers for the quick-edit popovers ------------------------------- //

    const { data: users = [] } = useQuery({
        queryKey: ['hr-users'],
        queryFn: () => fetchEmployeeUsers(),
    });
    const userById = useMemo(() => {
        const map = new Map<number, any>();
        users.forEach((u: any) => map.set(u.id, u));
        return map;
    }, [users]);

    const { data: allLabels = [] } = useQuery({
        queryKey: ['hr-labels'],
        queryFn: fetchLabels,
    });

    const invalidateTasks = () => queryClient.invalidateQueries({ queryKey: ['hr-tasks'] });

    const priorityMutation = useMutation({
        mutationFn: ({ id, priority }: { id: number; priority: TaskPriority }) =>
            updateTask(id, { priority }),
        onSuccess: invalidateTasks,
        onError: () => toast.error(t('tasks.pages.list.updateError', 'Не удалось обновить задачу')),
    });

    const assigneesMutation = useMutation({
        mutationFn: ({ id, assignees }: { id: number; assignees: Array<{ user_id: number; role: AssigneeRole }> }) =>
            updateTaskAssignees(id, assignees),
        onSuccess: invalidateTasks,
        onError: () => toast.error(t('tasks.pages.list.updateError', 'Не удалось обновить задачу')),
    });

    const supervisorMutation = useMutation({
        mutationFn: ({ id, userId }: { id: number; userId: number | null }) =>
            updateTaskSupervisor(id, userId),
        onSuccess: invalidateTasks,
        onError: () => toast.error(t('tasks.pages.list.updateError', 'Не удалось обновить задачу')),
    });

    const progressMutation = useMutation({
        mutationFn: ({ id, percent }: { id: number; percent: number }) =>
            updateTaskProgress(id, percent),
        onSuccess: invalidateTasks,
        onError: () => toast.error(t('tasks.pages.list.updateError', 'Не удалось обновить задачу')),
    });

    const labelsMutation = useMutation({
        mutationFn: ({ id, label_ids }: { id: number; label_ids: number[] }) =>
            updateTask(id, { label_ids } as any),
        onSuccess: invalidateTasks,
        onError: () => toast.error(t('tasks.pages.list.updateError', 'Не удалось обновить задачу')),
    });

    const onDragEnd = (result: DropResult) => {
        if (!result.destination) return;
        const { source, destination, draggableId } = result;
        if (source.droppableId === destination.droppableId && source.index === destination.index) return;

        const sourceCol = source.droppableId as TaskStatus;
        const destCol = destination.droppableId as TaskStatus;
        const newCols: Record<TaskStatus, Task[]> = { ...columns };

        // Locate the moved card by its id (draggableId) rather than by the
        // drag index — indexes are page-relative once pagination is on, so
        // splicing by index would target the wrong card in the full array.
        const movedId = Number(draggableId);
        const sourceTasks = [...newCols[sourceCol]];
        const movedPos = sourceTasks.findIndex(t => t.id === movedId);
        if (movedPos === -1) return;
        const [movedTask] = sourceTasks.splice(movedPos, 1);

        if (sourceCol !== destCol) {
            movedTask.status = destCol;
            const destTasks = [...newCols[destCol]];
            // Append to the destination column; exact ordering is cosmetic
            // and not persisted to the backend.
            destTasks.push(movedTask);
            newCols[sourceCol] = sourceTasks;
            newCols[destCol] = destTasks;
            setColumns(newCols);
            onStatusChange(movedId, destCol);
        } else {
            sourceTasks.splice(movedPos, 0, movedTask);
            newCols[sourceCol] = sourceTasks;
            setColumns(newCols);
        }
    };

    return (
        <DragDropContext onDragEnd={onDragEnd}>
            {/* Fixed-width columns (320px) that WRAP to the next row when the
                screen can't fit them all side by side. No horizontal scroll,
                no squishing — the number of columns per row follows the
                viewport width. Cards within a column paginate (6/page). */}
            <div className="flex flex-wrap gap-4 pb-4 w-full items-start content-start">
                {STATUS_ORDER.map(status => {
                    const colTasks = columns[status] ?? [];
                    const totalPages = Math.max(1, Math.ceil(colTasks.length / CARDS_PER_PAGE));
                    const page = Math.min(pages[status] ?? 0, totalPages - 1);
                    const pageStart = page * CARDS_PER_PAGE;
                    const visibleTasks = colTasks.slice(pageStart, pageStart + CARDS_PER_PAGE);

                    return (
                    <div
                        key={status}
                        className={`rounded-xl p-3 flex flex-col w-[320px] shrink-0 border ${STATUS_TINT[status]}`}
                    >
                        <div className="flex items-center justify-between mb-3 px-1">
                            <span className="font-semibold text-sm uppercase tracking-wider text-muted-foreground">
                                {t(`tasks.pages.list.status.${status}`, status)}
                            </span>
                            <Badge variant="secondary" className="rounded-full shadow-sm shrink-0">
                                {colTasks.length}
                            </Badge>
                        </div>

                        <Droppable droppableId={status}>
                            {(provided, snapshot) => (
                                <div
                                    ref={provided.innerRef}
                                    {...provided.droppableProps}
                                    className={`flex-1 flex flex-col gap-3 min-h-[100px] transition-colors rounded-lg ${snapshot.isDraggingOver ? 'bg-primary/5' : ''}`}
                                >
                                    {visibleTasks.map((task, index) => (
                                        <Draggable key={task.id} draggableId={String(task.id)} index={index}>
                                            {(provided, snapshot) => (
                                                <div
                                                    ref={provided.innerRef}
                                                    {...provided.draggableProps}
                                                    {...provided.dragHandleProps}
                                                    className="focus:outline-none"
                                                    style={provided.draggableProps.style}
                                                >
                                                    <Card
                                                        className={`hover:border-primary/50 transition-all shadow-sm ${snapshot.isDragging ? 'rotate-2 scale-105 shadow-md border-primary' : ''}`}
                                                        style={task.project ? { borderLeftWidth: 3, borderLeftColor: task.project_color || '#3b82f6' } : undefined}
                                                    >
                                                        <CardContent className="p-3 space-y-2">
                                                            {/* Project chip — only for project-attached tasks, so
                                                                standalone tasks are visually distinct (no chip). */}
                                                            {task.project_name && (
                                                                <Link
                                                                    to="/roadmap"
                                                                    onClick={(e) => e.stopPropagation()}
                                                                    className="inline-flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded max-w-full"
                                                                    style={{
                                                                        backgroundColor: `${task.project_color || '#3b82f6'}20`,
                                                                        color: task.project_color || '#3b82f6',
                                                                    }}
                                                                    title={task.project_name}
                                                                >
                                                                    <span className="truncate">{task.project_name}</span>
                                                                </Link>
                                                            )}

                                                            {/* Header: key + priority chip popover */}
                                                            <div className="flex justify-between items-start">
                                                                <Link
                                                                    to={`/tasks/${task.id}`}
                                                                    className="font-mono text-xs font-bold text-primary hover:underline"
                                                                >
                                                                    {task.key}
                                                                </Link>

                                                                <Popover>
                                                                    <PopoverTrigger asChild>
                                                                        <button
                                                                            type="button"
                                                                            className={`text-[10px] uppercase font-bold px-1.5 py-0.5 rounded ${PRIORITY_COLORS[task.priority]}`}
                                                                            onClick={(e) => e.stopPropagation()}
                                                                        >
                                                                            {task.priority}
                                                                        </button>
                                                                    </PopoverTrigger>
                                                                    <PopoverContent className="w-44 p-1" onClick={(e) => e.stopPropagation()}>
                                                                        {PRIORITIES.map(p => (
                                                                            <button
                                                                                key={p}
                                                                                type="button"
                                                                                className="w-full flex items-center justify-between text-xs px-2 py-1.5 rounded hover:bg-muted text-left"
                                                                                onClick={() => priorityMutation.mutate({ id: task.id, priority: p })}
                                                                            >
                                                                                <span className={`px-1.5 py-0.5 rounded text-[10px] uppercase font-bold ${PRIORITY_COLORS[p]}`}>{p}</span>
                                                                                {task.priority === p && <span className="text-primary">●</span>}
                                                                            </button>
                                                                        ))}
                                                                    </PopoverContent>
                                                                </Popover>
                                                            </div>

                                                            {/* Summary */}
                                                            <p className="text-sm font-medium line-clamp-2 leading-tight">
                                                                {task.summary}
                                                            </p>

                                                            {/* Progress bar (inline edit) */}
                                                            <Popover>
                                                                <PopoverTrigger asChild>
                                                                    <button
                                                                        type="button"
                                                                        className="w-full text-left"
                                                                        onClick={(e) => e.stopPropagation()}
                                                                    >
                                                                        <div className="flex items-center gap-1.5">
                                                                            <div className="flex-1 h-1.5 bg-muted rounded overflow-hidden">
                                                                                <div
                                                                                    className="h-full bg-primary"
                                                                                    style={{ width: `${task.progress_percent ?? 0}%` }}
                                                                                />
                                                                            </div>
                                                                            <span className="text-[10px] tabular-nums text-muted-foreground w-9 text-right">
                                                                                {task.progress_percent ?? 0}%
                                                                            </span>
                                                                        </div>
                                                                    </button>
                                                                </PopoverTrigger>
                                                                <PopoverContent className="w-56 p-3" onClick={(e) => e.stopPropagation()}>
                                                                    <ProgressEditor
                                                                        initial={task.progress_percent ?? 0}
                                                                        onCommit={(p) => progressMutation.mutate({ id: task.id, percent: p })}
                                                                    />
                                                                </PopoverContent>
                                                            </Popover>

                                                            {/* Labels row */}
                                                            {(task.labels?.length || allLabels.length > 0) && (
                                                                <Popover>
                                                                    <PopoverTrigger asChild>
                                                                        <button
                                                                            type="button"
                                                                            className="flex flex-wrap gap-1 cursor-pointer w-full"
                                                                            onClick={(e) => e.stopPropagation()}
                                                                        >
                                                                            {task.labels?.length ? task.labels.map(l => (
                                                                                <Badge
                                                                                    key={l.id}
                                                                                    variant="outline"
                                                                                    className="text-[10px] px-1.5 py-0"
                                                                                    style={{ borderColor: l.color, color: l.color }}
                                                                                >
                                                                                    {l.name}
                                                                                </Badge>
                                                                            )) : (
                                                                                <span className="text-[11px] text-muted-foreground inline-flex items-center gap-1">
                                                                                    <Tag className="h-3 w-3" /> {t('tasks.pages.list.addLabel', 'Метки')}
                                                                                </span>
                                                                            )}
                                                                        </button>
                                                                    </PopoverTrigger>
                                                                    <PopoverContent className="w-56 p-2" onClick={(e) => e.stopPropagation()}>
                                                                        <LabelsEditor
                                                                            taskLabelIds={(task.labels ?? []).map(l => l.id)}
                                                                            allLabels={allLabels}
                                                                            onCommit={(ids) => labelsMutation.mutate({ id: task.id, label_ids: ids })}
                                                                        />
                                                                    </PopoverContent>
                                                                </Popover>
                                                            )}

                                                            {/* Footer: type icon + supervisor chip + assignees avatars */}
                                                            <div className="flex items-center justify-between pt-1 border-t border-dashed border-muted">
                                                                <div className="flex items-center gap-2">
                                                                    {TYPE_ICONS[task.task_type]}

                                                                    <Popover>
                                                                        <PopoverTrigger asChild>
                                                                            <button
                                                                                type="button"
                                                                                className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground hover:bg-muted/80"
                                                                                onClick={(e) => e.stopPropagation()}
                                                                                title={t('tasks.pages.list.supervisor', 'Супервизор')}
                                                                            >
                                                                                <Shield className="h-3 w-3" />
                                                                                <span className="truncate max-w-[80px]">
                                                                                    {task.supervisor_name ?? t('tasks.pages.list.noSupervisor', 'Нет')}
                                                                                </span>
                                                                            </button>
                                                                        </PopoverTrigger>
                                                                        <PopoverContent className="w-60 p-2 max-h-72 overflow-y-auto" onClick={(e) => e.stopPropagation()}>
                                                                            <SupervisorEditor
                                                                                currentId={task.supervisor}
                                                                                users={users}
                                                                                onCommit={(uid) => supervisorMutation.mutate({ id: task.id, userId: uid })}
                                                                            />
                                                                        </PopoverContent>
                                                                    </Popover>
                                                                </div>

                                                                {/* Assignees avatar stack */}
                                                                <Popover>
                                                                    <PopoverTrigger asChild>
                                                                        <button
                                                                            type="button"
                                                                            className="flex -space-x-1.5"
                                                                            onClick={(e) => e.stopPropagation()}
                                                                            title={t('tasks.pages.list.assignees', 'Исполнители')}
                                                                        >
                                                                            {(task.assignees ?? []).length === 0 && (
                                                                                <div className="h-6 w-6 rounded-full bg-muted border border-background flex items-center justify-center">
                                                                                    <UserPlus className="h-3 w-3 text-muted-foreground" />
                                                                                </div>
                                                                            )}
                                                                            {(task.assignees ?? []).slice(0, 3).map(a => (
                                                                                <div
                                                                                    key={a.user_id}
                                                                                    className={`h-6 w-6 rounded-full border border-background flex items-center justify-center text-[10px] font-bold ${
                                                                                        a.role === 'primary'
                                                                                            ? 'bg-primary/20 text-primary ring-1 ring-primary'
                                                                                            : 'bg-muted text-muted-foreground'
                                                                                    }`}
                                                                                    title={a.name ?? `#${a.user_id}`}
                                                                                >
                                                                                    {initials(a.name)}
                                                                                </div>
                                                                            ))}
                                                                            {(task.assignees ?? []).length > 3 && (
                                                                                <div className="h-6 w-6 rounded-full bg-muted border border-background flex items-center justify-center text-[10px] font-bold text-muted-foreground">
                                                                                    +{(task.assignees ?? []).length - 3}
                                                                                </div>
                                                                            )}
                                                                        </button>
                                                                    </PopoverTrigger>
                                                                    <PopoverContent className="w-72 p-2 max-h-80 overflow-y-auto" onClick={(e) => e.stopPropagation()}>
                                                                        <AssigneesEditor
                                                                            currentAssignees={task.assignees ?? []}
                                                                            users={users}
                                                                            onCommit={(crew) => assigneesMutation.mutate({ id: task.id, assignees: crew })}
                                                                        />
                                                                    </PopoverContent>
                                                                </Popover>
                                                            </div>
                                                        </CardContent>
                                                    </Card>
                                                </div>
                                            )}
                                        </Draggable>
                                    ))}
                                    {provided.placeholder}
                                </div>
                            )}
                        </Droppable>

                        {/* Per-column pagination — "the rest" of the cards
                            move to the next page instead of an endless scroll. */}
                        {totalPages > 1 && (
                            <div className="flex items-center justify-between gap-1 mt-2 px-1">
                                <button
                                    type="button"
                                    disabled={page <= 0}
                                    onClick={() => setPages(prev => ({ ...prev, [status]: Math.max(0, (prev[status] ?? 0) - 1) }))}
                                    className="h-6 w-6 flex items-center justify-center rounded hover:bg-muted disabled:opacity-30 disabled:cursor-not-allowed"
                                    aria-label={t('common.prev', 'Назад')}
                                >
                                    <ChevronLeft className="h-3.5 w-3.5" />
                                </button>
                                <span className="text-[10px] text-muted-foreground tabular-nums">
                                    {page + 1} / {totalPages}
                                </span>
                                <button
                                    type="button"
                                    disabled={page >= totalPages - 1}
                                    onClick={() => setPages(prev => ({ ...prev, [status]: Math.min(totalPages - 1, (prev[status] ?? 0) + 1) }))}
                                    className="h-6 w-6 flex items-center justify-center rounded hover:bg-muted disabled:opacity-30 disabled:cursor-not-allowed"
                                    aria-label={t('common.next', 'Вперёд')}
                                >
                                    <ChevronRight className="h-3.5 w-3.5" />
                                </button>
                            </div>
                        )}
                    </div>
                    );
                })}
            </div>
        </DragDropContext>
    );
};

function buildColumns(tasks: Task[]): Record<TaskStatus, Task[]> {
    const cols: Record<TaskStatus, Task[]> = {
        backlog: [], todo: [], in_progress: [], in_review: [], blocked: [], done: [], cancelled: [],
    };
    tasks.forEach(task => {
        // Defensive: legacy 'open' / 'closed' rows from before migration 012
        // are coerced to the new vocabulary so the board still renders
        // them while a deployment is mid-rollout.
        const status = (
            task.status === ('open' as any) ? 'todo'
                : task.status === ('closed' as any) ? 'cancelled'
                    : task.status
        ) as TaskStatus;
        if (cols[status]) cols[status].push(task);
    });
    return cols;
}

/* ============================================================ */
/*  Quick-edit sub-components                                    */
/* ============================================================ */

const ProgressEditor: React.FC<{ initial: number; onCommit: (p: number) => void }> = ({ initial, onCommit }) => {
    const { t } = useTranslation();
    const [value, setValue] = useState(initial);
    useEffect(() => { setValue(initial); }, [initial]);
    return (
        <div className="space-y-3">
            <div className="flex items-center justify-between text-xs">
                <span className="text-muted-foreground">{t('tasks.pages.list.progress', 'Прогресс')}</span>
                <span className="font-bold tabular-nums">{value}%</span>
            </div>
            <Slider min={0} max={100} step={5} value={[value]} onValueChange={(v) => setValue(v[0] ?? 0)} />
            <Button size="sm" className="w-full h-7" onClick={() => onCommit(value)}>
                {t('common.save', 'Сохранить')}
            </Button>
        </div>
    );
};

const SupervisorEditor: React.FC<{
    currentId: number | null;
    users: any[];
    onCommit: (userId: number | null) => void;
}> = ({ currentId, users, onCommit }) => {
    const { t } = useTranslation();
    return (
        <div className="space-y-1">
            <button
                type="button"
                className="w-full text-left text-xs px-2 py-1.5 rounded hover:bg-muted flex items-center justify-between"
                onClick={() => onCommit(null)}
            >
                <span className="text-muted-foreground">{t('tasks.pages.list.noSupervisor', 'Нет супервизора')}</span>
                {currentId === null && <span className="text-primary">●</span>}
            </button>
            <div className="h-px bg-muted my-1" />
            {users.map((u: any) => (
                <button
                    key={u.id}
                    type="button"
                    className="w-full text-left text-xs px-2 py-1.5 rounded hover:bg-muted flex items-center justify-between"
                    onClick={() => onCommit(u.id)}
                >
                    <span className="truncate">{displayName(u)}</span>
                    {currentId === u.id && <span className="text-primary">●</span>}
                </button>
            ))}
        </div>
    );
};

const AssigneesEditor: React.FC<{
    currentAssignees: Array<{ user_id: number; role: AssigneeRole; name?: string | null }>;
    users: any[];
    onCommit: (crew: Array<{ user_id: number; role: AssigneeRole }>) => void;
}> = ({ currentAssignees, users, onCommit }) => {
    const { t } = useTranslation();
    const [crew, setCrew] = useState<Array<{ user_id: number; role: AssigneeRole }>>(
        currentAssignees.map(a => ({ user_id: a.user_id, role: a.role })),
    );
    useEffect(() => {
        setCrew(currentAssignees.map(a => ({ user_id: a.user_id, role: a.role })));
    }, [currentAssignees]);

    function toggle(userId: number) {
        setCrew(prev => {
            const found = prev.find(a => a.user_id === userId);
            if (found) return prev.filter(a => a.user_id !== userId);
            const role: AssigneeRole = prev.some(a => a.role === 'primary')
                ? 'collaborator'
                : 'primary';
            return [...prev, { user_id: userId, role }];
        });
    }
    function makePrimary(userId: number) {
        setCrew(prev => prev.map(a => ({
            ...a,
            role: a.user_id === userId ? 'primary' : 'collaborator',
        })));
    }

    return (
        <div className="space-y-2">
            <div className="text-[11px] text-muted-foreground px-1">
                {t('tasks.pages.list.createDialog.primaryHint', 'Звезда — основной исполнитель')}
            </div>
            <div className="max-h-48 overflow-y-auto">
                {users.map((u: any) => {
                    const picked = crew.find(a => a.user_id === u.id);
                    return (
                        <div
                            key={u.id}
                            className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-muted/50 cursor-pointer"
                            onClick={() => toggle(u.id)}
                        >
                            <Checkbox checked={!!picked} onCheckedChange={() => toggle(u.id)} />
                            <span className="flex-1 text-xs truncate">{displayName(u)}</span>
                            {picked && (
                                <button
                                    type="button"
                                    onClick={(e) => { e.stopPropagation(); makePrimary(u.id); }}
                                    className={`text-[10px] px-1.5 py-0.5 rounded ${
                                        picked.role === 'primary'
                                            ? 'bg-primary text-primary-foreground'
                                            : 'bg-muted text-muted-foreground'
                                    }`}
                                >
                                    {picked.role === 'primary' ? '★' : '☆'}
                                </button>
                            )}
                        </div>
                    );
                })}
            </div>
            <Button size="sm" className="w-full h-7" onClick={() => onCommit(crew)}>
                {t('common.save', 'Сохранить')}
            </Button>
        </div>
    );
};

const LabelsEditor: React.FC<{
    taskLabelIds: number[];
    allLabels: LabelType[];
    onCommit: (ids: number[]) => void;
}> = ({ taskLabelIds, allLabels, onCommit }) => {
    const { t } = useTranslation();
    const [selected, setSelected] = useState<Set<number>>(new Set(taskLabelIds));
    useEffect(() => { setSelected(new Set(taskLabelIds)); }, [taskLabelIds.join(',')]);

    function toggle(id: number) {
        setSelected(prev => {
            const next = new Set(prev);
            if (next.has(id)) next.delete(id);
            else next.add(id);
            return next;
        });
    }

    return (
        <div className="space-y-2">
            <div className="max-h-48 overflow-y-auto">
                {allLabels.length === 0 && (
                    <div className="text-xs text-muted-foreground p-2">
                        {t('common.empty', 'Нет данных')}
                    </div>
                )}
                {allLabels.map(l => (
                    <div
                        key={l.id}
                        className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-muted/50 cursor-pointer"
                        onClick={() => toggle(l.id)}
                    >
                        <Checkbox checked={selected.has(l.id)} onCheckedChange={() => toggle(l.id)} />
                        <Badge variant="outline" className="text-[10px]" style={{ borderColor: l.color, color: l.color }}>
                            {l.name}
                        </Badge>
                    </div>
                ))}
            </div>
            <Button size="sm" className="w-full h-7" onClick={() => onCommit(Array.from(selected))}>
                {t('common.save', 'Сохранить')}
            </Button>
        </div>
    );
};
