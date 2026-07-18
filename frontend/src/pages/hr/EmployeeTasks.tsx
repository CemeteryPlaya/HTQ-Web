import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { TasksLayout } from '@/components/tasks/TasksLayout';
import { KanbanBoard } from '@/components/tasks/KanbanBoard';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
    Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { toast } from 'sonner';
import {
    Search, Bug, BookOpen, Layers, CheckSquare, ListTodo, Check
} from 'lucide-react';
import { fetchTasks, updateTask } from '@/api/tasks';
import type { Task, TaskPriority, TaskStatus } from '@/types/tasks';
import type { UserProfile } from '@/types/userProfile';

/* ---- Constants ---- */

const PRIORITY_CONFIG: Record<TaskPriority, { color: string; icon: string }> = {
    critical: { color: 'bg-red-500 text-white', icon: '🔴' },
    high: { color: 'bg-orange-500 text-white', icon: '🟠' },
    medium: { color: 'bg-yellow-500 text-black', icon: '🟡' },
    low: { color: 'bg-blue-500 text-white', icon: '🔵' },
    trivial: { color: 'bg-gray-400 text-white', icon: '⚪' },
};

const STATUS_CONFIG: Record<TaskStatus, { color: string }> = {
    backlog: { color: 'bg-slate-400 text-white' },
    todo: { color: 'bg-slate-600 text-white' },
    in_progress: { color: 'bg-blue-600 text-white' },
    in_review: { color: 'bg-purple-500 text-white' },
    blocked: { color: 'bg-red-500 text-white' },
    done: { color: 'bg-green-500 text-white' },
    cancelled: { color: 'bg-gray-600 text-white' },
};

const TYPE_ICONS: Record<string, React.ReactNode> = {
    task: <CheckSquare className="h-4 w-4 text-blue-500" />,
    bug: <Bug className="h-4 w-4 text-red-500" />,
    story: <BookOpen className="h-4 w-4 text-green-500" />,
    epic: <Layers className="h-4 w-4 text-purple-500" />,
    subtask: <ListTodo className="h-4 w-4 text-gray-500" />,
};

interface Props {
    profile: UserProfile;
}

const EmployeeTasks: React.FC<Props> = ({ profile }) => {
    const { t } = useTranslation();
    const navigate = useNavigate();
    const queryClient = useQueryClient();
    const [search, setSearch] = useState('');
    const [activeTab, setActiveTab] = useState('my-tasks');
    const [viewMode, setViewMode] = useState<'table' | 'board'>('table');

    const currentUserDepartmentId = profile.department_id;
    const currentUserId = Number(profile.id);

    // Load tasks
    const { data: tasks = [], isLoading } = useQuery({
        queryKey: ['employee-tasks', activeTab],
        queryFn: async () => {
            const data = await fetchTasks(); // Using identical fetch method, backend handles scoping initially
            return data;
        },
    });

    // Accepting task immediately updates assignee and status
    const acceptMutation = useMutation({
        mutationFn: (taskToAccept: Task) => {
            return updateTask(taskToAccept.id, {
                assignee: currentUserId,
                status: (taskToAccept.status === 'todo' || taskToAccept.status === 'backlog')
                    ? 'in_progress'
                    : taskToAccept.status,
            } as Partial<Task>);
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['employee-tasks'] });
            toast.success(t('tasks.pages.detail.success'));
            setActiveTab('my-tasks');
        },
        onError: () => toast.error(t('tasks.pages.detail.error')),
    });

    const updateStatusMutation = useMutation({
        mutationFn: ({ id, status }: { id: number; status: TaskStatus }) => updateTask(id, { status }),
        onSuccess: () => queryClient.invalidateQueries({ queryKey: ['employee-tasks'] }),
        onError: () => toast.error(t('tasks.pages.list.updateError')),
    });

    // Filter tasks locally to serve tab functionalities
    const filteredTasks = tasks.filter((t_opt) => {
        const sMatch = t_opt.summary.toLowerCase().includes(search.toLowerCase()) ||
            t_opt.key.toLowerCase().includes(search.toLowerCase());
        if (!sMatch) return false;

        if (activeTab === 'my-tasks') {
            return (t_opt.assignee === currentUserId) || (t_opt.reporter === currentUserId);
        }

        if (activeTab === 'department-tasks') {
            const sameDepartment = currentUserDepartmentId
                ? t_opt.department === currentUserDepartmentId
                : Boolean(profile.department && t_opt.department_name === profile.department);
            return sameDepartment
                && (t_opt.status === 'todo' || t_opt.status === 'backlog')
                && !t_opt.assignee;
        }

        return true;
    });

    const renderTable = () => (
        <div className="overflow-x-auto">
            <Table>
                <TableHeader>
                    <TableRow>
                        <TableHead className="w-[100px]">{t('tasks.pages.list.table.type')}</TableHead>
                        <TableHead className="w-[110px]">{t('tasks.pages.list.table.key')}</TableHead>
                        <TableHead>{t('tasks.pages.list.table.summary')}</TableHead>
                        <TableHead className="w-[120px]">{t('tasks.pages.list.table.status')}</TableHead>
                        <TableHead className="w-[120px]">{t('tasks.pages.list.table.priority')}</TableHead>
                        <TableHead className="w-[150px]">{t('tasks.pages.list.table.assignee')}</TableHead>
                        <TableHead className="w-[100px]">{t('tasks.pages.list.table.dueDate')}</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {filteredTasks.length === 0 && (
                        <TableRow>
                            <TableCell colSpan={7} className="text-center py-8 text-muted-foreground">
                                Нет задач
                            </TableCell>
                        </TableRow>
                    )}
                    {filteredTasks.map((task) => (
                        <TableRow
                            key={task.id}
                            className="cursor-pointer hover:bg-muted/50"
                            onClick={() => navigate(`/tasks/${task.id}`)}
                        >
                            <TableCell>
                                <div className="flex items-center gap-1.5">
                                    {TYPE_ICONS[task.task_type]}
                                    <span className="text-xs text-muted-foreground">
                                        {t(`tasks.pages.list.type.${task.task_type}`)}
                                    </span>
                                </div>
                            </TableCell>
                            <TableCell>
                                <span className="font-mono text-sm font-medium text-primary">
                                    {task.key}
                                </span>
                            </TableCell>
                            <TableCell>
                                <div>
                                    <div className="font-medium">{task.summary}</div>
                                    {task.labels && task.labels.length > 0 && (
                                        <div className="flex gap-1 mt-1">
                                            {task.labels.map((l) => (
                                                <Badge
                                                    key={l.id}
                                                    variant="outline"
                                                    className="text-xs px-1.5 py-0"
                                                    style={{ borderColor: l.color, color: l.color }}
                                                >
                                                    {l.name}
                                                </Badge>
                                            ))}
                                        </div>
                                    )}
                                </div>
                            </TableCell>
                            <TableCell>
                                <Badge className={STATUS_CONFIG[task.status]?.color || ''}>
                                    {t(`tasks.pages.list.status.${task.status}`) || task.status}
                                </Badge>
                            </TableCell>
                            <TableCell>
                                <span className="text-sm">
                                    {PRIORITY_CONFIG[task.priority]?.icon}{' '}
                                    {t(`tasks.pages.list.priority.${task.priority}`) || task.priority}
                                </span>
                            </TableCell>
                            <TableCell className="text-sm">
                                {task.assignee_name ? (
                                    task.assignee_name
                                ) : (
                                    activeTab === 'department-tasks' ? (
                                        <Button
                                            size="sm"
                                            variant="secondary"
                                            className="h-7 px-2 text-xs"
                                            onClick={(e) => {
                                                e.stopPropagation();
                                                acceptMutation.mutate(task);
                                            }}
                                            disabled={acceptMutation.isPending}
                                        >
                                            <Check className="h-3 w-3 mr-1" />
                                            {t('tasks.pages.detail.acceptTask')}
                                        </Button>
                                    ) : (
                                        '—'
                                    )
                                )}
                            </TableCell>
                            <TableCell className="text-sm text-muted-foreground">
                                {task.due_date || '—'}
                            </TableCell>
                        </TableRow>
                    ))}
                </TableBody>
            </Table>
        </div>
    );

    return (
        <TasksLayout title={t('tasks.pages.list.title')} subtitle={t('tasks.pages.list.subtitle')}>
            <Card className="flex-1 w-full min-w-0 overflow-hidden">
                <CardContent className="p-4 w-full min-w-0">
                    <Tabs value={activeTab} onValueChange={setActiveTab}>
                        <div className="flex flex-col sm:flex-row gap-4 mb-4 items-center justify-between">
                            <TabsList>
                                <TabsTrigger value="my-tasks">Мои задачи</TabsTrigger>
                                <TabsTrigger value="department-tasks">Свободные задачи отдела</TabsTrigger>
                            </TabsList>

                            <div className="flex gap-2 w-full sm:w-auto items-center">
                                <div className="relative">
                                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                                    <Input
                                        placeholder={t('tasks.pages.list.search')}
                                        value={search}
                                        onChange={(e) => setSearch(e.target.value)}
                                        className="pl-10 w-full sm:w-64"
                                    />
                                </div>
                                <div className="flex bg-muted/50 p-1 rounded-md gap-1 border">
                                    <Button
                                        variant={viewMode === 'board' ? 'secondary' : 'ghost'}
                                        size="sm"
                                        className="h-7 text-xs"
                                        onClick={() => setViewMode('board')}
                                    >
                                        Kanban
                                    </Button>
                                    <Button
                                        variant={viewMode === 'table' ? 'secondary' : 'ghost'}
                                        size="sm"
                                        className="h-7 text-xs"
                                        onClick={() => setViewMode('table')}
                                    >
                                        Table
                                    </Button>
                                </div>
                            </div>
                        </div>

                        <TabsContent value="my-tasks" className="w-full min-w-0 overflow-hidden">
                            <div className="border rounded-md w-full min-w-0 overflow-hidden">
                                {isLoading ? (
                                    <div className="p-8 text-center text-muted-foreground">Loading...</div>
                                ) : viewMode === 'board' ? (
                                    <div className="-mx-2 -mb-2 p-2 min-w-0">
                                        <KanbanBoard
                                            tasks={filteredTasks}
                                            onStatusChange={(taskId, newStatus) => updateStatusMutation.mutate({ id: taskId, status: newStatus })}
                                        />
                                    </div>
                                ) : (
                                    renderTable()
                                )}
                            </div>
                        </TabsContent>

                        <TabsContent value="department-tasks" className="w-full min-w-0 overflow-hidden">
                            <div className="border rounded-md w-full min-w-0 overflow-hidden">
                                {isLoading ? (
                                    <div className="p-8 text-center text-muted-foreground">Loading...</div>
                                ) : viewMode === 'board' ? (
                                    <div className="-mx-2 -mb-2 p-2 min-w-0">
                                        <KanbanBoard
                                            tasks={filteredTasks}
                                            onStatusChange={(taskId, newStatus) => updateStatusMutation.mutate({ id: taskId, status: newStatus })}
                                        />
                                    </div>
                                ) : (
                                    renderTable()
                                )}
                            </div>
                        </TabsContent>
                    </Tabs>
                </CardContent>
            </Card>
        </TasksLayout>
    );
};

export default EmployeeTasks;
