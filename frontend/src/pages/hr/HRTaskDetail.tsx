import React, { useState, useRef } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { TasksLayout } from '@/components/tasks/TasksLayout';
import { CreateTaskModal } from '@/components/tasks/CreateTaskModal';
import { TaskAssignments } from '@/components/tasks/TaskAssignments';
import { TaskDailyReporting } from '@/components/tasks/TaskDailyReporting';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle, CardFooter } from '@/components/ui/card';
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
  Calendar, User, Building2, Tag, Clock, Plus,
} from 'lucide-react';
import {
  fetchTask, updateTask, addTaskComment, addTaskAttachment,
  fetchLabels, fetchProjects, fetchTaskTransitions, createTaskLink, deleteTaskLink
} from '@/api/tasks';
import { fetchDepartments, fetchEmployeeUsers } from '@/api/hr';
import api from '@/api/client';
import type { UserProfile } from '@/types/userProfile';
import {
  TASK_STATUS_ORDER, statusBadgeClass, statusLabel,
} from '@/lib/tasks/status';
import {
  TASK_PRIORITY, TASK_PRIORITY_ORDER, priorityLabel,
} from '@/lib/tasks/priority';
import type {
  Task, TaskPriority, TaskStatus,
  TaskComment as TComment,
} from '@/types/tasks';

/* ---- Config maps ---- */



// Keyed by slug; custom types fall back to a generic icon at call sites.
const TYPE_ICONS: Record<string, React.ReactNode> = {
  task: <CheckSquare className="h-5 w-5 text-blue-500" />,
  bug: <Bug className="h-5 w-5 text-red-500" />,
  story: <BookOpen className="h-5 w-5 text-green-500" />,
  epic: <Layers className="h-5 w-5 text-purple-500" />,
  subtask: <ListTodo className="h-5 w-5 text-gray-500" />,
};

/* ---- Component ---- */

const HRTaskDetail: React.FC = () => {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [commentText, setCommentText] = useState('');
  const [editingField, setEditingField] = useState<string | null>(null);
  const [editDesc, setEditDesc] = useState('');
  const [editSummary, setEditSummary] = useState('');

  const [linkIsAdding, setLinkIsAdding] = useState(false);
  const [linkType, setLinkType] = useState('blocks');
  const [linkTargetId, setLinkTargetId] = useState('');

  const [isCreateSubtaskOpen, setCreateSubtaskOpen] = useState(false);

  const taskId = Number(id);

  const { data: task, isLoading, error } = useQuery({
    queryKey: ['hr-task', taskId],
    queryFn: () => fetchTask(taskId),
    enabled: !!taskId,
  });

  const { data: transitions = [] } = useQuery({
    queryKey: ['task-transitions', taskId, task?.status],
    queryFn: () => fetchTaskTransitions(taskId),
    enabled: !!taskId && !!task,
  });

  const { data: departments = [] } = useQuery({
    queryKey: ['hr-departments'],
    queryFn: fetchDepartments,
  });

  const { data: projects = [] } = useQuery({
    queryKey: ['hr-projects'],
    queryFn: () => fetchProjects(),
  });

  const { data: profile } = useQuery({
    queryKey: ['profile'],
    queryFn: async () => {
      const res = await api.get<UserProfile>('users/v1/profile/me');
      return res.data;
    },
  });

  const { data: users = [] } = useQuery({
    queryKey: ['hr-users'],
    queryFn: () => fetchEmployeeUsers(),
  });

  const updateMutation = useMutation({
    mutationFn: (data: Partial<Task>) => updateTask(taskId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hr-task', taskId] });
      queryClient.invalidateQueries({ queryKey: ['hr-tasks'] });
      toast.success(t('tasks.pages.detail.success'));
      setEditingField(null);
    },
    onError: () => toast.error(t('tasks.pages.detail.error')),
  });

  const commentMutation = useMutation({
    mutationFn: (body: string) => addTaskComment(taskId, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hr-task', taskId] });
      setCommentText('');
      toast.success(t('tasks.pages.detail.commentSuccess'));
    },
    onError: () => toast.error(t('tasks.pages.detail.commentError')),
  });

  const attachMutation = useMutation({
    mutationFn: (file: File) => addTaskAttachment(taskId, file),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hr-task', taskId] });
      toast.success(t('tasks.pages.detail.attachSuccess'));
    },
    onError: () => toast.error(t('tasks.pages.detail.attachError')),
  });

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) attachMutation.mutate(file);
  }

  const linkMutation = useMutation({
    mutationFn: () => createTaskLink({ source: taskId, target: parseInt(linkTargetId, 10), link_type: linkType }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hr-task', taskId] });
      setLinkIsAdding(false);
      setLinkTargetId('');
      toast.success(t('tasks.pages.detail.linkSuccess', 'Связь добавлена'));
    },
    onError: (err: any) => {
      const msg = err.response?.data?.non_field_errors?.[0] || t('hr.taskDetail.linkError');
      toast.error(msg);
    },
  });

  const deleteLinkMutation = useMutation({
    mutationFn: (linkId: number) => deleteTaskLink(linkId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hr-task', taskId] });
      toast.success(t('tasks.pages.detail.linkDeleted', 'Связь удалена'));
    },
  });

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

      {/* Split layout */}
      <div className="grid gap-6 lg:grid-cols-[1fr_340px]">

        {/* ===== LEFT: Content ===== */}
        <div className="space-y-6">

          {/* Header */}
          <Card>
            <CardContent className="p-6">
              <div className="flex items-center gap-3 mb-4">
                {TYPE_ICONS[task.task_type] ?? (
                  <span
                    className="inline-block h-4 w-4 rounded-full"
                    style={{ backgroundColor: task.task_type_color || '#6b7280' }}
                  />
                )}
                {task.project_name && (
                  <Badge
                    variant="outline"
                    style={{ borderColor: task.project_color || undefined, color: task.project_color || undefined }}
                  >
                    {task.project_name}
                  </Badge>
                )}
                <span className="font-mono text-lg font-bold text-primary">{task.key}</span>
                <Badge className={statusBadgeClass(task.status)}>
                  {statusLabel(task.status, t)}
                </Badge>
              </div>

              {editingField === 'summary' ? (
                <div className="flex gap-2 items-center mb-2">
                  <Input
                    value={editSummary}
                    onChange={(e) => setEditSummary(e.target.value)}
                    className="text-lg font-semibold h-10 flex-1"
                    autoFocus
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        updateMutation.mutate({ summary: editSummary });
                      } else if (e.key === 'Escape') {
                        setEditingField(null);
                      }
                    }}
                  />
                  <Button size="sm" onClick={() => updateMutation.mutate({ summary: editSummary })}>
                    {t('tasks.pages.detail.save')}
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setEditingField(null)}>✕</Button>
                </div>
              ) : (
                <h2
                  className="text-2xl font-semibold mb-2 cursor-pointer hover:bg-muted/50 p-1 -ml-1 rounded transition-colors inline-block"
                  onClick={() => {
                    setEditSummary(task.summary);
                    setEditingField('summary');
                  }}
                  title={t('tasks.pages.detail.clickToEdit', 'Нажмите для изменения')}
                >
                  {task.summary}
                </h2>
              )}
            </CardContent>
          </Card>

          {/* Description */}
          <Card>
            <CardHeader><CardTitle>{t('tasks.pages.detail.description')}</CardTitle></CardHeader>
            <CardContent>
              {editingField === 'description' ? (
                <div className="space-y-2">
                  <Textarea
                    value={editDesc}
                    onChange={(e) => setEditDesc(e.target.value)}
                    rows={6}
                  />
                  <div className="flex gap-2">
                    <Button size="sm" onClick={() => {
                      updateMutation.mutate({ description: editDesc });
                    }}>{t('tasks.pages.detail.save')}</Button>
                    <Button size="sm" variant="outline" onClick={() => setEditingField(null)}>{t('tasks.pages.detail.cancel')}</Button>
                  </div>
                </div>
              ) : (
                <div
                  className="prose prose-sm dark:prose-invert cursor-pointer min-h-[40px] whitespace-pre-wrap"
                  onClick={() => {
                    setEditDesc(task.description || '');
                    setEditingField('description');
                  }}
                >
                  {task.description || <span className="text-muted-foreground italic">{t('tasks.pages.detail.descriptionPlaceholder')}</span>}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Ежедневная отчётность — сразу после описания: это ежедневное
              действие прораба, а не справка, и ниже подзадач его не найдут. */}
          <TaskDailyReporting
            task={task}
            onChanged={() => queryClient.invalidateQueries({
              queryKey: ['hr-task', taskId],
            })}
          />

          {/* Subtasks */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between py-4">
              <CardTitle className="text-lg">{t('tasks.pages.detail.subtasks')} ({task.subtasks?.length || 0})</CardTitle>
              {task.task_type !== 'subtask' && (
                <Button size="sm" variant="outline" onClick={() => setCreateSubtaskOpen(true)}>
                  + {t('tasks.pages.detail.addSubtask', 'Подзадача')}
                </Button>
              )}
            </CardHeader>
            <CardContent>
              {(!task.subtasks || task.subtasks.length === 0) ? (
                <div className="text-sm text-muted-foreground italic mb-2">
                  {t('hr.taskDetail.noSubtasks')}
                </div>
              ) : (
                <div className="space-y-2">
                  {task.subtasks.map((sub) => (
                    <Link
                      key={sub.id}
                      to={`/tasks/${sub.id}`}
                      className="flex items-center gap-3 p-2 rounded-lg hover:bg-muted transition-colors"
                    >
                      {TYPE_ICONS[sub.task_type]}
                      <span className="font-mono text-sm text-primary">{sub.key}</span>
                      <span className="text-sm flex-1">{sub.summary}</span>
                      <Badge className={statusBadgeClass(sub.status)} variant="secondary">
                        {statusLabel(sub.status, t)}
                      </Badge>
                    </Link>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Linked Tasks */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0">
              <CardTitle>{t('tasks.pages.detail.linkedTasks', { defaultValue: 'Связанные задачи' })}</CardTitle>
              <Button size="sm" variant="outline" onClick={() => setLinkIsAdding(!linkIsAdding)}>
                {linkIsAdding ? t('tasks.pages.detail.cancel') : t('tasks.pages.detail.addLink', 'Добавить связь')}
              </Button>
            </CardHeader>
            <CardContent>
              {linkIsAdding && (
                <div className="flex items-center gap-2 mb-4 p-3 border rounded-lg bg-muted/50">
                  <Select value={linkType} onValueChange={setLinkType}>
                    <SelectTrigger className="w-[150px]"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="blocks">{t('hr.taskDetail.blocks')}</SelectItem>
                      <SelectItem value="is_blocked_by">{t('hr.taskDetail.blockedBy')}</SelectItem>
                      <SelectItem value="relates_to">{t('hr.taskDetail.relatesTo')}</SelectItem>
                      <SelectItem value="duplicates">{t('hr.taskDetail.duplicates')}</SelectItem>
                    </SelectContent>
                  </Select>
                  <Input
                    placeholder={t('hr.taskDetail.targetIdPlaceholder')}
                    value={linkTargetId}
                    onChange={e => setLinkTargetId(e.target.value)}
                    className="w-[220px]"
                  />
                  <Button size="sm" onClick={() => linkMutation.mutate()} disabled={!linkTargetId || linkMutation.isPending}>
                    {t('tasks.pages.detail.save')}
                  </Button>
                </div>
              )}

              {(!task.outgoing_links?.length && !task.incoming_links?.length) ? (
                <p className="text-muted-foreground text-sm">{t('tasks.pages.detail.emptyLinks', 'Нет связанных задач')}</p>
              ) : (
                <div className="space-y-2">
                  {task.outgoing_links?.map((link) => (
                    <div key={`out-${link.id}`} className="flex items-center gap-3 p-2 rounded-lg hover:bg-muted transition-colors border text-sm">
                      <span className="font-medium text-xs text-muted-foreground uppercase px-2 py-1 bg-secondary rounded">
                        {link.link_type}
                      </span>
                      <Link to={`/tasks/${link.target}`} className="font-mono text-primary flex-none">{link.target_key}</Link>
                      <span className="truncate flex-1">{link.target_summary}</span>
                      <Button variant="ghost" size="sm" onClick={() => deleteLinkMutation.mutate(link.id)}>✕</Button>
                    </div>
                  ))}
                  {task.incoming_links?.map((link) => (
                    <div key={`in-${link.id}`} className="flex items-center gap-3 p-2 rounded-lg hover:bg-muted transition-colors border text-sm">
                      <span className="font-medium text-xs text-muted-foreground uppercase px-2 py-1 bg-secondary rounded">
                        is_{link.link_type}_by
                      </span>
                      <Link to={`/tasks/${link.source}`} className="font-mono text-primary flex-none">{link.source_key}</Link>
                      <span className="truncate flex-1">{link.source_summary}</span>
                    </div>
                  ))}
                </div>
              )}
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

          {/* Activities */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Clock className="h-4 w-4" />
                {t('tasks.pages.detail.history', 'История изменений')}
              </CardTitle>
            </CardHeader>
            <CardContent>
              {(!task.activities || task.activities.length === 0) ? (
                <p className="text-muted-foreground text-sm">{t('tasks.pages.detail.emptyHistory', 'Нет истории изменений')}</p>
              ) : (
                <div className="space-y-3">
                  {task.activities.map((act) => (
                    <div key={act.id} className="text-sm border-l-2 pl-3 pb-1 border-muted">
                      <div className="flex items-center gap-2 text-muted-foreground mb-1">
                        <span className="font-medium text-foreground">{act.actor_name || t('tasks.pages.detail.system', 'Система')}</span>
                        <span className="text-xs">{new Date(act.created_at).toLocaleString('ru')}</span>
                      </div>
                      <p>
                        {t('tasks.pages.detail.changedField', 'Изменил(а)')} <strong>{t(`hr.tasks.fields.${act.field_name}`, act.field_name)}</strong>
                        <br />
                        <span className="text-muted-foreground line-through mr-1">{act.old_value || '—'}</span>
                        <span>→</span>
                        <span className="ml-1 font-medium text-primary">{act.new_value || '—'}</span>
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* ===== RIGHT: Details sidebar ===== */}
        <div className="space-y-4">
          <Card>
            <CardHeader><CardTitle className="text-sm uppercase tracking-wider">{t('tasks.pages.detail.details')}</CardTitle></CardHeader>
            <CardContent className="space-y-4">

              {/* Status */}
              <div>
                <Label className="text-xs text-muted-foreground uppercase">{t('tasks.pages.detail.status')}</Label>
                <Select
                  value={task.status}
                  onValueChange={(v) => updateMutation.mutate({ status: v as TaskStatus })}
                >
                  <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {TASK_STATUS_ORDER.map((k) => (
                      <SelectItem
                        key={k}
                        value={k}
                        disabled={transitions.length > 0 && !transitions.includes(k as TaskStatus)}
                      >
                        {statusLabel(k, t)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {/* Priority */}
              <div>
                <Label className="text-xs text-muted-foreground uppercase">{t('tasks.pages.detail.priority')}</Label>
                <Select
                  value={task.priority}
                  onValueChange={(v) => updateMutation.mutate({ priority: v as TaskPriority })}
                >
                  <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {TASK_PRIORITY_ORDER.map((k) => (
                      <SelectItem key={k} value={k}>
                        {TASK_PRIORITY[k].icon} {priorityLabel(k, t)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <Separator />

              {/* Assignee */}
              <div>
                <Label className="text-xs text-muted-foreground uppercase flex items-center gap-1">
                  <User className="h-3 w-3" /> {t('tasks.pages.detail.assignee')}
                </Label>
                <Select
                  value={task.assignee ? String(task.assignee) : 'none'}
                  onValueChange={(v) => updateMutation.mutate({
                    assignee: v === 'none' ? null : Number(v),
                  } as any)}
                >
                  <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">{t('tasks.pages.detail.unassigned')}</SelectItem>
                    {users.map((u) => (
                      <SelectItem key={u.id} value={String(u.id)}>
                        {u.full_name || u.username}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

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
                <Select
                  value={task.department ? String(task.department) : 'none'}
                  onValueChange={(v) => updateMutation.mutate({
                    department: v === 'none' ? null : Number(v),
                  } as any)}
                >
                  <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">{t('tasks.pages.detail.noDepartment')}</SelectItem>
                    {departments.map((d) => (
                      <SelectItem key={d.id} value={String(d.id)}>{d.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {/* Project */}
              <div>
                <Label className="text-xs text-muted-foreground uppercase flex items-center gap-1">
                  <Tag className="h-3 w-3" /> {t('tasks.pages.detail.project', 'Проект')}
                </Label>
                <Select
                  value={task.project ? String(task.project) : 'none'}
                  onValueChange={(v) => updateMutation.mutate({
                    project: v === 'none' ? null : Number(v),
                  } as any)}
                >
                  <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="none">{t('tasks.pages.detail.noProject', 'Без проекта')}</SelectItem>
                    {projects.map((p) => (
                      <SelectItem key={p.id} value={String(p.id)}>
                        <span className="inline-flex items-center gap-2">
                          <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: p.color }} />
                          {p.name}
                        </span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <Separator />

              {/* Labels */}
              <div>
                <Label className="text-xs text-muted-foreground uppercase">{t('tasks.pages.detail.labels')}</Label>
                <div className="flex flex-wrap gap-1 mt-1">
                  {task.labels && task.labels.length > 0 ? task.labels.map((l) => (
                    <Badge
                      key={l.id}
                      variant="outline"
                      style={{ borderColor: l.color, color: l.color }}
                    >
                      {l.name}
                    </Badge>
                  )) : (
                    <span className="text-sm text-muted-foreground">{t('tasks.pages.detail.noLabels')}</span>
                  )}
                </div>
              </div>

              <Separator />

              {/* Dates */}
              <div>
                <Label className="text-xs text-muted-foreground uppercase flex items-center gap-1">
                  <Calendar className="h-3 w-3" /> {t('tasks.pages.detail.startDate')}
                </Label>
                <div className="flex flex-col gap-1">
                  <Input
                    type="date"
                    className="mt-1"
                    value={task.start_date || ''}
                    onChange={(e) => updateMutation.mutate({ start_date: e.target.value || null } as any)}
                  />
                  {task.task_type === 'epic' && task.effective_start_date && task.effective_start_date !== task.start_date && (
                    <span className="text-xs text-amber-600 dark:text-amber-500">
                      {t('hr.taskDetail.approxStart', { date: task.effective_start_date })}
                    </span>
                  )}
                </div>
              </div>

              <div>
                <Label className="text-xs text-muted-foreground uppercase flex items-center gap-1 mt-3">
                  <Calendar className="h-3 w-3" /> {t('tasks.pages.detail.dueDate')}
                </Label>
                <div className="flex flex-col gap-1">
                  <Input
                    type="date"
                    className="mt-1"
                    value={task.due_date || ''}
                    onChange={(e) => updateMutation.mutate({ due_date: e.target.value || null } as any)}
                  />
                  {task.task_type === 'epic' && task.effective_due_date && task.effective_due_date !== task.due_date && (
                    <span className="text-xs text-amber-600 dark:text-amber-500">
                      {t('hr.taskDetail.approxDue', { date: task.effective_due_date })}
                    </span>
                  )}
                  {task.date_warnings && task.date_warnings.length > 0 && (
                    <div className="mt-1 space-y-1">
                      {task.date_warnings.map((w, idx) => (
                        <div key={idx} className="text-xs text-red-600 bg-red-50 dark:bg-red-950/30 p-1.5 rounded border border-red-200 dark:border-red-900 flex items-start gap-1">
                          <span>⚠️</span>
                          <span>{w.message}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              <Separator />

              {/* Timestamps */}
              <div className="space-y-1 text-xs text-muted-foreground">
                <div className="flex items-center gap-1">
                  <Clock className="h-3 w-3" />
                  {t('tasks.pages.detail.created')}: {new Date(task.created_at).toLocaleString('ru')}
                </div>
                <div className="flex items-center gap-1">
                  <Clock className="h-3 w-3" />
                  {t('tasks.pages.detail.updated')}: {new Date(task.updated_at).toLocaleString('ru')}
                </div>
                {task.completed_at && (
                  <div className="flex items-center gap-1">
                    <Clock className="h-3 w-3" />
                    {t('tasks.pages.detail.completed')}: {new Date(task.completed_at).toLocaleString('ru')}
                  </div>
                )}
              </div>

            </CardContent>
            <CardFooter>
              <Button
                variant="outline"
                className="w-full"
                onClick={() => setCreateSubtaskOpen(true)}
              >
                <Plus className="h-4 w-4 mr-2" /> {t('tasks.pages.detail.addSubtask')}
              </Button>
            </CardFooter>
          </Card>

          <TaskAssignments taskId={task.id} />
        </div>
      </div>

      <CreateTaskModal
        open={isCreateSubtaskOpen}
        onOpenChange={setCreateSubtaskOpen}
        defaultParent={taskId}
        defaultProject={task?.project ?? undefined}
      />
    </TasksLayout>
  );
};

export default HRTaskDetail;
