import React, { useState, useEffect, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { ChevronDown, X, Plus } from 'lucide-react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Slider } from '@/components/ui/slider';
import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { toast } from 'sonner';

import {
    createTask, fetchProjects, fetchSites, fetchTaskTypes, createTaskType,
    fetchContractors, fetchContractorWorkers, fetchRoadmaps, fetchSiteBlocks,
} from '@/api/tasks';
import { fetchDepartments, fetchEmployees } from '@/api/hr';
import { TASK_PRIORITY, TASK_PRIORITY_ORDER } from '@/lib/tasks/priority';
import type { Task, TaskPriority, TaskStatus, AssigneeRole, TaskTypeRef } from '@/types/tasks';


const STATUS_KEYS: TaskStatus[] = [
    'backlog', 'todo', 'in_progress', 'in_review', 'blocked', 'done', 'cancelled',
];

interface AssigneeDraft {
    user_id: number;
    role: AssigneeRole;
}

export interface CreateTaskModalProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    defaultParent?: number;
    defaultProject?: number;
    defaultAssignee?: number;
    defaultDepartment?: number;
}

export const CreateTaskModal: React.FC<CreateTaskModalProps> = ({
    open, onOpenChange, defaultParent, defaultProject, defaultAssignee, defaultDepartment,
}) => {
    const { t } = useTranslation();
    const queryClient = useQueryClient();

    const [form, setForm] = useState({
        summary: '',
        description: '',
        // ``task_type`` here is the *slug* from the registry. We resolve
        // it server-side; defaulting to ``task`` matches the seeded row.
        task_type: 'task' as string,
        priority: 'medium' as TaskPriority,
        status: 'todo' as TaskStatus,
        supervisor: '' as string,
        // ``projectMode`` is the toggle the user explicitly asked for:
        // 'standalone' (Свободная задача) means no project; 'attached'
        // surfaces the project picker.
        projectMode: (defaultProject ? 'attached' : 'standalone') as 'standalone' | 'attached',
        project: defaultProject ? String(defaultProject) : '',
        site: '',
        roadmap: '',
        site_block: '',
        contractor: '',
        contractor_worker: '',
        parent: defaultParent || undefined,
        due_date: '',
        start_date: '',
        progress_percent: 0,
    });

    const [assigneeDraft, setAssigneeDraft] = useState<AssigneeDraft[]>(
        defaultAssignee ? [{ user_id: defaultAssignee, role: 'primary' }] : [],
    );

    // Multi-department selection. Drives BOTH the task's departments and
    // the candidate pool for supervisor / assignee pickers.
    const [departmentIds, setDepartmentIds] = useState<number[]>(
        defaultDepartment ? [defaultDepartment] : [],
    );

    // New-type inline create state. Slug is auto-generated server-side.
    const [newType, setNewType] = useState({ open: false, name: '', color: '#6b7280' });

    useEffect(() => {
        if (open) {
            setForm(prev => ({
                ...prev,
                parent: defaultParent || prev.parent,
                project: defaultProject ? String(defaultProject) : prev.project,
                projectMode: defaultProject ? 'attached' : prev.projectMode,
                task_type: defaultParent ? 'subtask' : prev.task_type,
            }));
            if (defaultDepartment) {
                setDepartmentIds(prev => (prev.length ? prev : [defaultDepartment]));
            }
            if (defaultAssignee) {
                setAssigneeDraft(prev =>
                    prev.length ? prev : [{ user_id: defaultAssignee, role: 'primary' }],
                );
            }
        }
    }, [open, defaultParent, defaultAssignee, defaultDepartment, defaultProject]);

    const { data: departments = [] } = useQuery({ queryKey: ['hr-departments'], queryFn: fetchDepartments, enabled: open });
    const { data: projects = [] } = useQuery({ queryKey: ['hr-projects'], queryFn: () => fetchProjects(), enabled: open });
    const { data: taskTypes = [] } = useQuery({ queryKey: ['hr-task-types'], queryFn: fetchTaskTypes, enabled: open });
    const { data: sites = [] } = useQuery({ queryKey: ['sites'], queryFn: () => fetchSites(), enabled: open });
    // Роудмапы сужены до выбранного проекта, блоки — до выбранного объекта:
    // то же правило, что на сервере, иначе форма предлагала бы вариант,
    // который потом вернёт 400.
    const { data: roadmaps = [] } = useQuery({
        queryKey: ['roadmaps', form.project],
        queryFn: () => fetchRoadmaps({ project_id: Number(form.project) }),
        enabled: open && !!form.project,
    });
    const { data: siteBlocks = [] } = useQuery({
        queryKey: ['site-blocks', form.site],
        queryFn: () => fetchSiteBlocks(Number(form.site)),
        enabled: open && !!form.site,
    });
    const { data: contractors = [] } = useQuery({
        queryKey: ['contractors'],
        queryFn: () => fetchContractors({ status: 'active' }),
        enabled: open,
    });
    // Люди грузятся только для выбранной организации: справочник всех
    // представителей сразу никому не нужен, а выбор из чужой компании —
    // ошибка, которую проще не дать совершить.
    const { data: contractorWorkers = [] } = useQuery({
        queryKey: ['contractor-workers', form.contractor],
        queryFn: () => fetchContractorWorkers(Number(form.contractor)),
        enabled: open && Boolean(form.contractor),
    });

    // Список объектов сужается до объектов выбранного проекта — зеркало
    // серверного правила. Проект без объектов (все существующие на момент
    // выката) разрешает любой, поэтому там показываем полный справочник.
    const selectedProject = form.projectMode === 'attached' && form.project
        ? projects.find((p: any) => String(p.id) === form.project)
        : undefined;
    const projectSiteIds: number[] = selectedProject?.site_ids ?? [];
    const availableSites = projectSiteIds.length
        ? sites.filter((s) => projectSiteIds.includes(s.id))
        : sites;

    // Candidate users for supervisor / assignees come from the selected
    // departments only — fetch employees per department and merge, keeping
    // those that have a linked platform account (user_id).
    const deptKey = [...departmentIds].sort((a, b) => a - b).join(',');
    const { data: users = [], isLoading: usersLoading } = useQuery({
        queryKey: ['task-create-employees', deptKey],
        enabled: open && departmentIds.length > 0,
        queryFn: async () => {
            const lists = await Promise.all(
                departmentIds.map(id => fetchEmployees({ department_id: String(id) })),
            );
            const map = new Map<number, { id: number; full_name: string; username?: string }>();
            lists.flat().forEach((e: any) => {
                const uid = e.user_id ?? e.user;
                if (uid && !map.has(uid)) {
                    map.set(uid, { id: uid, full_name: e.full_name, username: e.username });
                }
            });
            return Array.from(map.values());
        },
    });

    const userById = useMemo(() => {
        const map = new Map<number, { id: number; username?: string; full_name?: string }>();
        users.forEach((u: any) => map.set(u.id, u));
        return map;
    }, [users]);

    const noDeptSelected = departmentIds.length === 0;

    function toggleDepartment(id: number) {
        setDepartmentIds(prev =>
            prev.includes(id) ? prev.filter(d => d !== id) : [...prev, id],
        );
    }

    const primaryAssignee = assigneeDraft.find(a => a.role === 'primary');

    const createTypeMutation = useMutation({
        mutationFn: () => createTaskType({
            name: newType.name.trim(),
            color: newType.color,
        }),
        onSuccess: (created: TaskTypeRef) => {
            queryClient.invalidateQueries({ queryKey: ['hr-task-types'] });
            setForm(prev => ({ ...prev, task_type: created.slug }));
            setNewType({ open: false, name: '', color: '#6b7280' });
            toast.success(t('tasks.types.created', 'Тип создан'));
        },
        onError: (e: any) => {
            const msg = e?.response?.data?.detail || t('tasks.types.createError', 'Не удалось создать тип');
            toast.error(String(msg));
        },
    });

    const createMutation = useMutation({
        mutationFn: (payload: Partial<Task>) => createTask(payload),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['hr-tasks'] });
            if (defaultParent) queryClient.invalidateQueries({ queryKey: ['hr-task', String(defaultParent)] });
            queryClient.invalidateQueries({ queryKey: ['hr-projects'] });
            onOpenChange(false);
            setForm({
                summary: '', description: '', task_type: 'task', priority: 'medium',
                status: 'todo', supervisor: '',
                projectMode: 'standalone', project: '', roadmap: '', site: '',
                site_block: '',
                contractor: '', contractor_worker: '',
                due_date: '', start_date: '',
                parent: undefined, progress_percent: 0,
            });
            setAssigneeDraft([]);
            setDepartmentIds([]);
            toast.success(t('tasks.pages.list.createDialog.success', 'Задача создана'));
        },
        onError: () => toast.error(t('tasks.pages.list.createDialog.error', 'Ошибка при создании задачи')),
    });

    function toggleAssignee(userId: number) {
        setAssigneeDraft(prev => {
            const found = prev.find(a => a.user_id === userId);
            if (found) return prev.filter(a => a.user_id !== userId);
            const role: AssigneeRole = prev.some(a => a.role === 'primary') ? 'collaborator' : 'primary';
            return [...prev, { user_id: userId, role }];
        });
    }

    function setPrimary(userId: number) {
        setAssigneeDraft(prev => prev.map(a => ({
            ...a, role: a.user_id === userId ? 'primary' : 'collaborator',
        })));
    }

    function removeAssignee(userId: number) {
        setAssigneeDraft(prev => prev.filter(a => a.user_id !== userId));
    }

    function handleCreate() {
        if (!form.summary.trim()) {
            toast.error(t('tasks.pages.list.createDialog.summaryRequired', 'Заголовок обязателен'));
            return;
        }
        const payload: Record<string, any> = {
            summary: form.summary,
            description: form.description,
            // Backend resolves the slug to task_type_id.
            task_type: form.task_type,
            priority: form.priority,
            status: form.status,
            progress_percent: form.progress_percent,
        };
        if (form.supervisor) payload.supervisor_id = Number(form.supervisor);
        if (primaryAssignee) payload.assignee_id = primaryAssignee.user_id;
        if (assigneeDraft.length) payload.assignees = assigneeDraft;
        if (departmentIds.length) payload.department_ids = departmentIds;
        if (form.projectMode === 'attached' && form.project) {
            payload.project = Number(form.project);
        }
        if (form.site) payload.site = Number(form.site);
        // Роудмап задаёт проект и объект на сервере — шлём как есть.
        if (form.roadmap) payload.roadmap = Number(form.roadmap);
        if (form.site_block) payload.site_block = Number(form.site_block);
        if (form.contractor) payload.contractor = Number(form.contractor);
        if (form.contractor_worker) {
            payload.contractor_worker = Number(form.contractor_worker);
        }
        if (form.parent) payload.parent = form.parent;
        if (form.due_date) payload.due_date = form.due_date;
        if (form.start_date) payload.start_date = form.start_date;

        createMutation.mutate(payload as Partial<Task>);
    }

    function displayName(u: any): string {
        return u?.full_name || u?.username || `User #${u?.id ?? '?'}`;
    }

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
                <DialogHeader>
                    <DialogTitle>{t('tasks.pages.list.createDialog.title', 'Создать задачу')}</DialogTitle>
                </DialogHeader>

                <div className="grid gap-4 py-2">
                    <div>
                        <Label>{t('tasks.pages.list.createDialog.summary', 'Заголовок')}</Label>
                        <Input
                            value={form.summary}
                            onChange={(e) => setForm({ ...form, summary: e.target.value })}
                            placeholder={t('tasks.pages.list.createDialog.summaryPlaceholder', 'Короткое и понятное название')}
                            autoFocus
                        />
                    </div>

                    <div>
                        <Label>{t('tasks.pages.list.createDialog.description', 'Описание')}</Label>
                        <Textarea
                            value={form.description}
                            onChange={(e) => setForm({ ...form, description: e.target.value })}
                            placeholder={t('tasks.pages.list.createDialog.descriptionPlaceholder', 'Подробное описание задачи...')}
                            rows={4}
                        />
                    </div>

                    {/* Type (registry) + Priority */}
                    <div className="grid grid-cols-2 gap-4">
                        <div>
                            <div className="flex items-center justify-between mb-1">
                                <Label>{t('tasks.pages.list.createDialog.type', 'Тип задачи')}</Label>
                                <Popover open={newType.open} onOpenChange={(o) => setNewType(prev => ({ ...prev, open: o }))}>
                                    <PopoverTrigger asChild>
                                        <Button variant="ghost" size="sm" className="h-7 px-2 text-xs gap-1">
                                            <Plus className="h-3 w-3" />
                                            {t('tasks.types.create', 'Создать тип')}
                                        </Button>
                                    </PopoverTrigger>
                                    <PopoverContent className="w-72 p-3 space-y-2">
                                        <div>
                                            <Label className="text-xs">{t('tasks.types.name', 'Название')}</Label>
                                            <Input
                                                value={newType.name}
                                                onChange={(e) => setNewType(prev => ({ ...prev, name: e.target.value }))}
                                                placeholder={t('tasks.types.namePlaceholder', 'Обслуживание')}
                                                className="h-8 text-sm"
                                                autoFocus
                                            />
                                            <p className="text-[10px] text-muted-foreground mt-1">
                                                {t('tasks.types.slugAuto', 'Идентификатор сгенерируется автоматически')}
                                            </p>
                                        </div>
                                        <div className="flex items-center gap-2">
                                            <Label className="text-xs">{t('tasks.types.color', 'Цвет')}</Label>
                                            <input
                                                type="color"
                                                value={newType.color}
                                                onChange={(e) => setNewType(prev => ({ ...prev, color: e.target.value }))}
                                                className="h-7 w-12 border rounded"
                                            />
                                        </div>
                                        <Button
                                            size="sm"
                                            className="w-full"
                                            onClick={() => createTypeMutation.mutate()}
                                            disabled={!newType.name.trim() || createTypeMutation.isPending}
                                        >
                                            {createTypeMutation.isPending
                                                ? t('common.saving', 'Сохранение...')
                                                : t('common.create', 'Создать')}
                                        </Button>
                                    </PopoverContent>
                                </Popover>
                            </div>
                            <Select
                                value={form.task_type}
                                onValueChange={(v) => setForm({ ...form, task_type: v })}
                                disabled={!!defaultParent}
                            >
                                <SelectTrigger><SelectValue /></SelectTrigger>
                                <SelectContent>
                                    {taskTypes.map((tt: TaskTypeRef) => (
                                        <SelectItem key={tt.id} value={tt.slug}>
                                            <span className="inline-flex items-center gap-2">
                                                <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: tt.color }} />
                                                {tt.name}
                                            </span>
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>

                        <div>
                            <Label>{t('tasks.pages.list.createDialog.priority', 'Приоритет')}</Label>
                            <Select
                                value={form.priority}
                                onValueChange={(v) => setForm({ ...form, priority: v as TaskPriority })}
                            >
                                <SelectTrigger><SelectValue /></SelectTrigger>
                                <SelectContent>
                                    {TASK_PRIORITY_ORDER.map((k) => (
                                        <SelectItem key={k} value={k}>{TASK_PRIORITY[k].icon} {t(`tasks.pages.list.priority.${k}`, k)}</SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>
                    </div>

                    {/* Project attachment toggle — explicit "standalone vs attached" */}
                    <div className="border rounded-lg p-3 space-y-3 bg-muted/20">
                        <Label className="text-sm font-semibold">
                            {t('tasks.pages.list.createDialog.projectGroup', 'Принадлежность к проекту')}
                        </Label>
                        <RadioGroup
                            value={form.projectMode}
                            onValueChange={(v) => setForm({ ...form, projectMode: v as 'standalone' | 'attached' })}
                            className="flex gap-6"
                        >
                            <div className="flex items-center gap-2">
                                <RadioGroupItem value="standalone" id="proj-standalone" />
                                <Label htmlFor="proj-standalone" className="cursor-pointer text-sm">
                                    {t('tasks.pages.list.createDialog.standalone', 'Свободная задача')}
                                </Label>
                            </div>
                            <div className="flex items-center gap-2">
                                <RadioGroupItem value="attached" id="proj-attached" />
                                <Label htmlFor="proj-attached" className="cursor-pointer text-sm">
                                    {t('tasks.pages.list.createDialog.attached', 'Привязать к проекту')}
                                </Label>
                            </div>
                        </RadioGroup>
                        {form.projectMode === 'attached' && (
                            <Select value={form.project} onValueChange={(v) => setForm({ ...form, project: v })}>
                                <SelectTrigger>
                                    <SelectValue placeholder={t('tasks.pages.list.createDialog.selectProject', 'Выбрать проект')} />
                                </SelectTrigger>
                                <SelectContent>
                                    {projects.length === 0 && (
                                        <div className="text-xs text-muted-foreground p-2">
                                            {t('tasks.pages.list.createDialog.noProjects', 'Нет проектов. Создайте на странице «Проекты».')}
                                        </div>
                                    )}
                                    {projects.map((p: any) => (
                                        <SelectItem key={p.id} value={String(p.id)}>
                                            <span className="inline-flex items-center gap-2">
                                                <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: p.color }} />
                                                {p.name}
                                            </span>
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        )}

                        {/* Объект работ. Когда выбран проект, список сужен до
                            его объектов — то же правило, что и на сервере
                            (site_service.resolve_task_site), иначе форма
                            предлагала бы вариант, который потом даст 400. */}
                        <div className="mt-3">
                            <Label className="text-xs text-muted-foreground">
                                {t('tasks.pages.sites.siteField', 'Объект')}
                            </Label>
                            <Select
                                value={form.site}
                                onValueChange={(v) => setForm({ ...form, site: v === '__none__' ? '' : v })}
                            >
                                <SelectTrigger className="mt-1">
                                    <SelectValue placeholder={t('tasks.pages.sites.selectSite', 'Выбрать объект')} />
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="__none__">
                                        {t('tasks.pages.sites.withoutSite', 'Без объекта')}
                                    </SelectItem>
                                    {availableSites.length === 0 && (
                                        <div className="text-xs text-muted-foreground p-2">
                                            {t('tasks.pages.sites.noneForProject', 'У проекта нет объектов')}
                                        </div>
                                    )}
                                    {availableSites.map((s: any) => (
                                        <SelectItem key={s.id} value={String(s.id)}>
                                            <span className="inline-flex items-center gap-2">
                                                <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: s.color }} />
                                                {s.name}
                                            </span>
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>

                        {/* Роудмап — пакет работ внутри проекта. Виден только
                            когда проект выбран: без проекта список пуст, и
                            пустой селект только мешает. Смена роудмапа
                            сбрасывает блок: он принадлежит объекту, а объект
                            приедет с сервера уже от нового пакета. */}
                        {form.projectMode === 'attached' && form.project && (
                            <div className="mt-3">
                                <Label className="text-xs text-muted-foreground">
                                    {t('tasks.pages.roadmaps.editTitle', 'Роудмап')}
                                </Label>
                                <Select
                                    value={form.roadmap || '__none__'}
                                    onValueChange={(v) => setForm({
                                        ...form,
                                        roadmap: v === '__none__' ? '' : v,
                                        site_block: '',
                                    })}
                                >
                                    <SelectTrigger className="mt-1">
                                        <SelectValue placeholder={t('tasks.pages.roadmaps.selectRoadmap', 'Выберите роудмап')} />
                                    </SelectTrigger>
                                    <SelectContent>
                                        <SelectItem value="__none__">
                                            {t('tasks.pages.roadmaps.noRoadmap', 'Без роудмапа')}
                                        </SelectItem>
                                        {roadmaps.length === 0 && (
                                            <div className="text-xs text-muted-foreground p-2">
                                                {t('tasks.pages.roadmaps.empty', 'Роудмапов пока нет')}
                                            </div>
                                        )}
                                        {roadmaps.map((r) => (
                                            <SelectItem key={r.id} value={String(r.id)}>
                                                <span className="inline-flex items-center gap-2">
                                                    <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: r.color }} />
                                                    {r.name}
                                                    <span className="text-xs text-muted-foreground">
                                                        · {r.site_name} / {r.site_block_name}
                                                    </span>
                                                </span>
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </div>
                        )}

                        {/* Блок объекта — «развезти 250 валов на блок I».
                            Только на задаче: у роудмапа блока нет, он идёт по
                            объекту целиком. */}
                        {form.site && (
                            <div className="mt-3">
                                <Label className="text-xs text-muted-foreground">
                                    {t('tasks.pages.blocks.block', 'Блок')}
                                </Label>
                                <Select
                                    value={form.site_block || '__none__'}
                                    onValueChange={(v) => setForm({
                                        ...form, site_block: v === '__none__' ? '' : v,
                                    })}
                                >
                                    <SelectTrigger className="mt-1">
                                        <SelectValue placeholder={t('tasks.pages.blocks.selectBlock', 'Выберите блок')} />
                                    </SelectTrigger>
                                    <SelectContent>
                                        <SelectItem value="__none__">
                                            {t('tasks.pages.blocks.noBlock', 'Без блока')}
                                        </SelectItem>
                                        {siteBlocks.length === 0 && (
                                            <div className="text-xs text-muted-foreground p-2">
                                                {t('tasks.pages.blocks.empty', 'Блоков пока нет')}
                                            </div>
                                        )}
                                        {siteBlocks.map((b) => (
                                            <SelectItem key={b.id} value={String(b.id)}>
                                                {b.name}
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </div>
                        )}
                    </div>

                    {/* Исполнитель: своя команда или субподрядчик. */}
                    <div className="grid grid-cols-2 gap-3">
                        <div>
                            <Label>{t('tasks.pages.contractors.one', 'Подрядчик')}</Label>
                            <Select
                                value={form.contractor || '__none__'}
                                onValueChange={(v) => setForm({
                                    ...form,
                                    contractor: v === '__none__' ? '' : v,
                                    // Человек принадлежит организации — смена
                                    // организации обнуляет выбор.
                                    contractor_worker: '',
                                })}
                            >
                                <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="__none__">
                                        {t('tasks.pages.contractors.ownCrew', 'Своя команда')}
                                    </SelectItem>
                                    {contractors.map((c: any) => (
                                        <SelectItem key={c.id} value={String(c.id)}>{c.name}</SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>
                        {form.contractor && (
                            <div>
                                <Label>{t('tasks.pages.contractors.worker', 'Представитель')}</Label>
                                <Select
                                    value={form.contractor_worker || '__none__'}
                                    onValueChange={(v) => setForm({
                                        ...form,
                                        contractor_worker: v === '__none__' ? '' : v,
                                    })}
                                >
                                    <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                                    <SelectContent>
                                        <SelectItem value="__none__">
                                            {t('tasks.pages.contractors.noWorker', 'Не указан')}
                                        </SelectItem>
                                        {contractorWorkers.map((w: any) => (
                                            <SelectItem key={w.id} value={String(w.id)}>
                                                {w.full_name}
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </div>
                        )}
                    </div>

                    {/* Departments (multi) — must be chosen BEFORE supervisor /
                        assignees: the people pickers below list only members of
                        the selected departments. */}
                    <div>
                        <Label>{t('tasks.pages.list.createDialog.departments', 'Отделы')}</Label>
                        <Popover>
                            <PopoverTrigger asChild>
                                <Button variant="outline" className="w-full justify-between font-normal">
                                    <span className="truncate text-left">
                                        {departmentIds.length === 0
                                            ? t('tasks.pages.list.createDialog.selectDepartmentsPlaceholder', 'Выберите отделы')
                                            : t('tasks.pages.list.createDialog.selectedCount', '{{count}} выбрано', { count: departmentIds.length })}
                                    </span>
                                    <ChevronDown className="h-4 w-4 opacity-50" />
                                </Button>
                            </PopoverTrigger>
                            <PopoverContent className="w-[320px] p-0 max-h-72 overflow-y-auto">
                                {departments.length === 0 && (
                                    <div className="p-3 text-sm text-muted-foreground">{t('common.empty', 'Нет данных')}</div>
                                )}
                                {departments.map((d: any) => {
                                    const picked = departmentIds.includes(d.id);
                                    return (
                                        <div
                                            key={d.id}
                                            className="flex items-center gap-2 px-3 py-2 hover:bg-muted/40 cursor-pointer"
                                            onClick={() => toggleDepartment(d.id)}
                                        >
                                            <Checkbox checked={picked} onCheckedChange={() => toggleDepartment(d.id)} />
                                            <span className="flex-1 text-sm truncate">{d.name}</span>
                                        </div>
                                    );
                                })}
                            </PopoverContent>
                        </Popover>
                        {departmentIds.length > 0 && (
                            <div className="flex flex-wrap gap-1 mt-2">
                                {departmentIds.map((id) => {
                                    const d = departments.find((x: any) => x.id === id);
                                    return (
                                        <Badge key={id} variant="secondary" className="gap-1">
                                            <span>{d ? d.name : `#${id}`}</span>
                                            <button
                                                type="button"
                                                className="ml-1 opacity-70 hover:opacity-100"
                                                onClick={() => toggleDepartment(id)}
                                            >
                                                <X className="h-3 w-3" />
                                            </button>
                                        </Badge>
                                    );
                                })}
                            </div>
                        )}
                    </div>

                    {/* Multi-assignee + supervisor */}
                    <div className="grid grid-cols-2 gap-4">
                        <div>
                            <Label>{t('tasks.pages.list.createDialog.assignees', 'Исполнители')}</Label>
                            <Popover>
                                <PopoverTrigger asChild>
                                    <Button variant="outline" className="w-full justify-between font-normal">
                                        <span className="truncate text-left">
                                            {assigneeDraft.length === 0
                                                ? t('tasks.pages.list.createDialog.selectAssigneesPlaceholder', 'Не назначены')
                                                : t('tasks.pages.list.createDialog.selectedCount', '{{count}} выбрано', { count: assigneeDraft.length })}
                                        </span>
                                        <ChevronDown className="h-4 w-4 opacity-50" />
                                    </Button>
                                </PopoverTrigger>
                                <PopoverContent className="w-[320px] p-0 max-h-72 overflow-y-auto">
                                    <div className="p-2 text-xs text-muted-foreground border-b">
                                        {t('tasks.pages.list.createDialog.primaryHint', 'Звезда — основной исполнитель')}
                                    </div>
                                    {noDeptSelected ? (
                                        <div className="p-3 text-sm text-muted-foreground">
                                            {t('tasks.pages.list.createDialog.selectDeptFirst', 'Сначала выберите отдел')}
                                        </div>
                                    ) : usersLoading ? (
                                        <div className="p-3 text-sm text-muted-foreground">{t('common.loading', 'Загрузка...')}</div>
                                    ) : users.length === 0 ? (
                                        <div className="p-3 text-sm text-muted-foreground">{t('tasks.pages.list.createDialog.noEmployees', 'В выбранных отделах нет сотрудников')}</div>
                                    ) : null}
                                    {!noDeptSelected && users.map((u: any) => {
                                        const picked = assigneeDraft.find(a => a.user_id === u.id);
                                        return (
                                            <div
                                                key={u.id}
                                                className="flex items-center gap-2 px-3 py-2 hover:bg-muted/40 cursor-pointer"
                                                onClick={() => toggleAssignee(u.id)}
                                            >
                                                <Checkbox checked={!!picked} onCheckedChange={() => toggleAssignee(u.id)} />
                                                <span className="flex-1 text-sm truncate">{displayName(u)}</span>
                                                {picked && (
                                                    <button
                                                        type="button"
                                                        onClick={(e) => { e.stopPropagation(); setPrimary(u.id); }}
                                                        className={`text-xs px-1.5 py-0.5 rounded ${
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
                                </PopoverContent>
                            </Popover>
                            {assigneeDraft.length > 0 && (
                                <div className="flex flex-wrap gap-1 mt-2">
                                    {assigneeDraft.map((a) => {
                                        const u = userById.get(a.user_id);
                                        return (
                                            <Badge key={a.user_id} variant={a.role === 'primary' ? 'default' : 'secondary'} className="gap-1">
                                                {a.role === 'primary' && <span>★</span>}
                                                <span>{u ? displayName(u) : `#${a.user_id}`}</span>
                                                <button
                                                    type="button"
                                                    className="ml-1 opacity-70 hover:opacity-100"
                                                    onClick={() => removeAssignee(a.user_id)}
                                                >
                                                    <X className="h-3 w-3" />
                                                </button>
                                            </Badge>
                                        );
                                    })}
                                </div>
                            )}
                        </div>

                        <div>
                            <Label>{t('tasks.pages.list.createDialog.supervisor', 'Супервизор')}</Label>
                            <Select
                                value={form.supervisor}
                                onValueChange={(v) => setForm({ ...form, supervisor: v })}
                                disabled={noDeptSelected}
                            >
                                <SelectTrigger>
                                    <SelectValue placeholder={
                                        noDeptSelected
                                            ? t('tasks.pages.list.createDialog.selectDeptFirst', 'Сначала выберите отдел')
                                            : t('tasks.pages.list.createDialog.selectSupervisorPlaceholder', 'Не выбран')
                                    } />
                                </SelectTrigger>
                                <SelectContent>
                                    {users.length === 0 && (
                                        <div className="p-2 text-xs text-muted-foreground">
                                            {t('tasks.pages.list.createDialog.noEmployees', 'В выбранных отделах нет сотрудников')}
                                        </div>
                                    )}
                                    {users.map((u: any) => (
                                        <SelectItem key={u.id} value={String(u.id)}>{displayName(u)}</SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>
                    </div>

                    <div>
                        <Label>{t('tasks.pages.list.createDialog.status', 'Статус')}</Label>
                        <Select value={form.status} onValueChange={(v) => setForm({ ...form, status: v as TaskStatus })}>
                            <SelectTrigger><SelectValue /></SelectTrigger>
                            <SelectContent>
                                {STATUS_KEYS.map((k) => (
                                    <SelectItem key={k} value={k}>{t(`tasks.pages.list.status.${k}`, k)}</SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                        <div>
                            <Label>{t('tasks.pages.list.createDialog.startDate', 'Дата начала')}</Label>
                            <Input
                                type="date"
                                value={form.start_date}
                                onChange={(e) => setForm({ ...form, start_date: e.target.value })}
                            />
                        </div>
                        <div>
                            <Label>{t('tasks.pages.list.createDialog.dueDate', 'Дедлайн')}</Label>
                            <Input
                                type="date"
                                value={form.due_date}
                                onChange={(e) => setForm({ ...form, due_date: e.target.value })}
                            />
                        </div>
                    </div>

                    <div>
                        <Label>
                            {t('tasks.pages.list.createDialog.progress', 'Прогресс')}: {form.progress_percent}%
                        </Label>
                        <Slider
                            min={0}
                            max={100}
                            step={5}
                            value={[form.progress_percent]}
                            onValueChange={(v) => setForm({ ...form, progress_percent: v[0] ?? 0 })}
                            className="mt-3"
                        />
                    </div>
                </div>

                <DialogFooter>
                    <Button variant="outline" onClick={() => onOpenChange(false)}>
                        {t('tasks.pages.list.createDialog.cancel', 'Отмена')}
                    </Button>
                    <Button onClick={handleCreate} disabled={createMutation.isPending}>
                        {createMutation.isPending
                            ? t('tasks.pages.list.createDialog.submitting', 'Создание...')
                            : t('tasks.pages.list.createDialog.submit', 'Создать')}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
};
