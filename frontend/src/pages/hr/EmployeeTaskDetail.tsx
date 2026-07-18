import React, { useState, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { TasksLayout } from '@/components/tasks/TasksLayout';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { Separator } from '@/components/ui/separator';
import {
    Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { toast } from 'sonner';
import {
    ArrowLeft, Paperclip, MessageSquare, Send, Upload,
    Bug, BookOpen, Layers, CheckSquare, ListTodo,
    User, Building2, Tag, Clock, Check, AlertTriangle
} from 'lucide-react';
import {
    fetchTask, updateTask, addTaskComment, addTaskAttachment
} from '@/api/tasks';
import type { UserProfile } from '@/types/userProfile';
import type { Task, TaskPriority, TaskStatus } from '@/types/tasks';

/* ---- Config Maps ---- */

const PRIORITY_CONFIG: Record<TaskPriority, { icon: string }> = {
    critical: { icon: '🔴' },
    high: { icon: '🟠' },
    medium: { icon: '🟡' },
    low: { icon: '🔵' },
    trivial: { icon: '⚪' },
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
    task: <CheckSquare className="h-5 w-5 text-blue-500" />,
    bug: <Bug className="h-5 w-5 text-red-500" />,
    story: <BookOpen className="h-5 w-5 text-green-500" />,
    epic: <Layers className="h-5 w-5 text-purple-500" />,
    subtask: <ListTodo className="h-5 w-5 text-gray-500" />,
};

interface Props {
    profile: UserProfile;
}

const EmployeeTaskDetail: React.FC<Props> = ({ profile }) => {
    const { t } = useTranslation();
    const { id } = useParams<{ id: string }>();
    const navigate = useNavigate();
    const queryClient = useQueryClient();
    const fileInputRef = useRef<HTMLInputElement>(null);

    const [commentText, setCommentText] = useState('');
    const taskId = Number(id);

    const { data: task, isLoading, error } = useQuery({
        queryKey: ['employee-task', taskId],
        queryFn: () => fetchTask(taskId),
        enabled: !!taskId,
    });

    const currentUserDepartmentId = profile.department_id;
    const currentUserId = Number(profile.id);

    const isAssignedToCurrentUser = task?.assignee === currentUserId;
    const isDepartmentTask = currentUserDepartmentId
        ? task?.department === currentUserDepartmentId
        : Boolean(profile.department && task?.department_name === profile.department);

    // Render "Accept" button conditionally
    const shouldShowAcceptButton = task &&
        isDepartmentTask &&
        (task.status === 'todo' || task.status === 'backlog') &&
        !task.assignee;

    const updateMutation = useMutation({
        mutationFn: (data: Partial<Task>) => updateTask(taskId, data),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['employee-task', taskId] });
            queryClient.invalidateQueries({ queryKey: ['employee-tasks'] });
            toast.success(t('tasks.pages.detail.success'));
        },
        onError: () => toast.error(t('tasks.pages.detail.error')),
    });

    const commentMutation = useMutation({
        mutationFn: (body: string) => addTaskComment(taskId, body),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['employee-task', taskId] });
            setCommentText('');
            toast.success(t('tasks.pages.detail.commentSuccess'));
        },
        onError: () => toast.error(t('tasks.pages.detail.commentError')),
    });

    const attachMutation = useMutation({
        mutationFn: (file: File) => addTaskAttachment(taskId, file),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['employee-task', taskId] });
            toast.success(t('tasks.pages.detail.attachSuccess'));
        },
        onError: () => toast.error(t('tasks.pages.detail.attachError')),
    });

    function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
        const file = e.target.files?.[0];
        if (file) attachMutation.mutate(file);
    }

    if (isLoading) {
        return (
            <TasksLayout title={t('tasks.pages.detail.loading')}>
                <div className="text-center py-12 text-muted-foreground">{t('tasks.pages.detail.loading')}</div>
            </TasksLayout>
        );
    }

    if (error || !task) {
        return (
            <TasksLayout title={t('tasks.pages.detail.error')}>
                <div className="text-center py-12 text-red-500">{t('tasks.pages.detail.notFound')}</div>
            </TasksLayout>
        );
    }

    return (
        <TasksLayout title={task.key} subtitle={task.summary}>
            {/* Back link */}
            <Button variant="ghost" size="sm" onClick={() => navigate('/tasks')} className="mb-2">
                <ArrowLeft className="h-4 w-4 mr-1" /> {t('tasks.pages.detail.backToList')}
            </Button>

            <div className="grid gap-6 lg:grid-cols-[1fr_340px]">
                {/* ===== LEFT: Content ===== */}
                <div className="space-y-6">
                    <Card>
                        <CardContent className="p-6">
                            <div className="flex items-center gap-3 mb-4">
                                {TYPE_ICONS[task.task_type]}
                                <span className="font-mono text-lg font-bold text-primary">{task.key}</span>
                                <Badge className={STATUS_CONFIG[task.status]?.color}>
                                    {t(`tasks.pages.list.status.${task.status}`)}
                                </Badge>
                            </div>
                            <h2 className="text-2xl font-semibold mb-2">{task.summary}</h2>
                        </CardContent>
                    </Card>

                    <Card>
                        <CardHeader><CardTitle>{t('tasks.pages.detail.description')}</CardTitle></CardHeader>
                        <CardContent>
                            <div className="prose prose-sm dark:prose-invert min-h-[40px] whitespace-pre-wrap">
                                {task.description || <span className="text-muted-foreground italic">{t('tasks.pages.detail.noDescription', 'Нет описания')}</span>}
                            </div>
                        </CardContent>
                    </Card>

                    {/* Attachments */}
                    <Card>
                        <CardHeader>
                            <CardTitle className="flex items-center justify-between">
                                <span className="flex items-center gap-2">
                                    <Paperclip className="h-4 w-4" />
                                    {t('tasks.pages.detail.attachments')} ({task.attachments?.length || 0})
                                </span>
                                <Button size="sm" variant="outline" onClick={() => fileInputRef.current?.click()}>
                                    <Upload className="h-4 w-4 mr-1" /> {t('tasks.pages.detail.attach')}
                                </Button>
                                <input ref={fileInputRef} type="file" className="hidden" onChange={handleFileChange} />
                            </CardTitle>
                        </CardHeader>
                        <CardContent>
                            {(!task.attachments || task.attachments.length === 0) ? (
                                <p className="text-muted-foreground text-sm">{t('tasks.pages.detail.emptyAttachments')}</p>
                            ) : (
                                <div className="space-y-2">
                                    {task.attachments.map((att) => (
                                        <div key={att.id} className="flex items-center gap-3 p-2 rounded border">
                                            <Paperclip className="h-4 w-4 text-muted-foreground" />
                                            <a href={att.file} target="_blank" rel="noreferrer"
                                                className="text-sm font-medium text-primary hover:underline flex-1">
                                                {att.filename}
                                            </a>
                                            <span className="text-xs text-muted-foreground">
                                                {att.uploaded_by_name} · {new Date(att.created_at).toLocaleDateString('ru')}
                                            </span>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </CardContent>
                    </Card>

                    {/* Comments */}
                    <Card>
                        <CardHeader>
                            <CardTitle className="flex items-center gap-2">
                                <MessageSquare className="h-4 w-4" />
                                {t('tasks.pages.detail.comments')} ({task.comments?.length || 0})
                            </CardTitle>
                        </CardHeader>
                        <CardContent>
                            <div className="space-y-4">
                                {task.comments?.map((comment) => (
                                    <div key={comment.id} className="border rounded-lg p-3">
                                        <div className="flex items-center gap-2 mb-1">
                                            <span className="font-medium text-sm">{comment.author_name || t('tasks.pages.detail.unassigned')}</span>
                                            <span className="text-xs text-muted-foreground">
                                                {new Date(comment.created_at).toLocaleString('ru')}
                                            </span>
                                        </div>
                                        <p className="text-sm whitespace-pre-wrap">{comment.body}</p>
                                    </div>
                                ))}

                                <Separator />

                                <div className="flex gap-2">
                                    <Textarea
                                        value={commentText}
                                        onChange={(e) => setCommentText(e.target.value)}
                                        placeholder={t('tasks.pages.detail.commentPlaceholder')}
                                        rows={2}
                                        className="flex-1"
                                    />
                                    <Button
                                        size="sm"
                                        disabled={!commentText.trim() || commentMutation.isPending}
                                        onClick={() => commentMutation.mutate(commentText)}
                                    >
                                        <Send className="h-4 w-4" />
                                    </Button>
                                </div>
                            </div>
                        </CardContent>
                    </Card>
                </div>

                {/* ===== RIGHT: Details sidebar ===== */}
                <div className="space-y-4">
                    <Card>
                        <CardHeader><CardTitle className="text-sm uppercase tracking-wider">{t('tasks.pages.detail.details')}</CardTitle></CardHeader>
                        <CardContent className="space-y-4">

                            {/* Assignee / Accept Task */}
                            <div className="p-3 bg-muted/30 rounded-lg border">
                                <Label className="text-xs text-muted-foreground uppercase flex items-center gap-1 mb-2">
                                    <User className="h-3 w-3" /> {t('tasks.pages.detail.assignee')}
                                </Label>
                                <div className="text-sm font-medium">
                                    {task.assignee_name || t('tasks.pages.detail.unassigned')}
                                </div>
                                {shouldShowAcceptButton && (
                                    <Button
                                        size="sm"
                                        className="w-full mt-3"
                                        onClick={() => {
                                            updateMutation.mutate({
                                                assignee: currentUserId,
                                                status: (task.status === 'todo' || task.status === 'backlog')
                                                    ? 'in_progress'
                                                    : task.status,
                                            } as Partial<Task>);
                                        }}
                                        disabled={updateMutation.isPending}
                                    >
                                        <Check className="h-4 w-4 mr-2" />
                                        {t('tasks.pages.detail.acceptTask')}
                                    </Button>
                                )}
                            </div>

                            {/* Status */}
                            <div>
                                <Label className="text-xs text-muted-foreground uppercase">{t('tasks.pages.detail.status')}</Label>
                                {isAssignedToCurrentUser ? (
                                    <Select
                                        value={task.status}
                                        onValueChange={(v) => updateMutation.mutate({ status: v as TaskStatus })}
                                    >
                                        <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                                        <SelectContent>
                                            {Object.keys(STATUS_CONFIG).map((k) => (
                                                <SelectItem key={k} value={k}>{t(`tasks.pages.list.status.${k}`)}</SelectItem>
                                            ))}
                                        </SelectContent>
                                    </Select>
                                ) : (
                                    <div className="mt-1">
                                        <Badge className={STATUS_CONFIG[task.status]?.color} variant="secondary">
                                            {t(`tasks.pages.list.status.${task.status}`)}
                                        </Badge>
                                    </div>
                                )}
                            </div>

                            {/* Priority */}
                            <div>
                                <Label className="text-xs text-muted-foreground uppercase">{t('tasks.pages.detail.priority')}</Label>
                                <div className="text-sm mt-1 flex items-center gap-1">
                                    {PRIORITY_CONFIG[task.priority]?.icon} {t(`tasks.pages.list.priority.${task.priority}`)}
                                </div>
                            </div>

                            <Separator />

                            {/* Reporter */}
                            <div>
                                <Label className="text-xs text-muted-foreground uppercase">{t('tasks.pages.detail.reporter')}</Label>
                                <p className="text-sm mt-1">{task.reporter_name || '—'}</p>
                            </div>

                            <Separator />

                            {/* Department */}
                            <div>
                                <Label className="text-xs text-muted-foreground uppercase flex items-center gap-1">
                                    <Building2 className="h-3 w-3" /> {t('tasks.pages.detail.department')}
                                </Label>
                                <p className="text-sm mt-1">{task.department_name || '—'}</p>
                            </div>

                            {/* Date Rollups & Warnings */}
                            {task.date_warnings && task.date_warnings.length > 0 && (
                                <div className="p-3 bg-red-500/10 border border-red-500/20 text-red-600 rounded-md text-sm flex flex-col gap-1">
                                    <div className="flex items-center gap-2 font-medium">
                                        <AlertTriangle className="h-4 w-4" />
                                        <span>Конфликт сроков</span>
                                    </div>
                                    <ul className="list-disc pl-6 space-y-1 mt-1 text-xs">
                                        {task.date_warnings.map((w, idx) => (
                                            <li key={idx}>{w.message}</li>
                                        ))}
                                    </ul>
                                </div>
                            )}

                            {/* Dates Container */}
                            <div className="space-y-3">
                                <div className="grid grid-cols-2 gap-4">
                                    <div>
                                        <Label className="text-xs text-muted-foreground uppercase flex items-center gap-1">
                                            <Clock className="h-3 w-3" /> Старт
                                        </Label>
                                        <div className="mt-1">
                                            <p className="text-sm">
                                                {task.start_date || '—'}
                                            </p>
                                            {task.task_type === 'epic' && task.effective_start_date && task.effective_start_date !== task.start_date && (
                                                <p className="text-xs text-green-600 font-medium mt-0.5" title="Вычислено по вложенным задачам">
                                                    Эфф: {task.effective_start_date}
                                                </p>
                                            )}
                                        </div>
                                    </div>

                                    <div>
                                        <Label className="text-xs text-muted-foreground uppercase flex items-center gap-1">
                                            <Clock className="h-3 w-3" /> {t('tasks.pages.list.table.dueDate')}
                                        </Label>
                                        <div className="mt-1">
                                            <p className="text-sm">
                                                {task.due_date || '—'}
                                            </p>
                                            {task.task_type === 'epic' && task.effective_due_date && task.effective_due_date !== task.due_date && (
                                                <p className="text-xs text-green-600 font-medium mt-0.5" title="Вычислено по вложенным задачам">
                                                    Эфф: {task.effective_due_date}
                                                </p>
                                            )}
                                        </div>
                                    </div>
                                </div>
                            </div>

                        </CardContent>
                    </Card>
                </div>
            </div>
        </TasksLayout>
    );
};

export default EmployeeTaskDetail;
