import React from 'react';
import { NavLink } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
    User as UserIcon,
    Settings,
    MessageSquare,
    Video,
    Mail,
    Calendar,
    FolderClosed,
    CheckSquare,
    Map as MapIcon,
    BarChart3,
    Newspaper,
    Layers,
    Inbox,
    Users,
    Building2,
    Briefcase,
    Clock,
    FileText,
    History,
    ClipboardList,
    Archive,
    KeyRound,
    Handshake,
    Link2,
    Network,
    SlidersHorizontal,
    UserCog,
    UserPlus,
    MessagesSquare,
    Mail as MailIcon,
    ServerCog,
    Activity,
    ExternalLink,
    type LucideIcon,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';

import api from '@/api/client';
import { apiPath } from '@/api/endpoints';
import { Badge } from '@/components/ui/badge';
import { useHRLevel } from '@/hooks/useHRLevel';
import { hasEmployeeTaskAccessFromParts } from '@/lib/auth/roles';
import { grafanaSsoUrl } from '@/lib/monitoring';
import { cn } from '@/lib/utils';

type Props = {
    roles?: string[];
    department?: string;
    position?: string;
};

// ── Role buckets — mirror values returned by user-service
// (services/user/app/api/v1/profile.py:_roles_for): "admin" for is_superuser,
// "staff" for is_staff-only, "user" otherwise. ────────────────────────────────
const ADMIN_ROLES = ['admin', 'superuser'];
const STAFF_OR_ADMIN_ROLES = [...ADMIN_ROLES, 'staff'];
const HR_ROLES = [
    ...STAFF_OR_ADMIN_ROLES,
    'hr_manager', 'senior_hr', 'junior_hr', 'senior_manager', 'junior_manager',
];
const EDITOR_ROLES = [...STAFF_OR_ADMIN_ROLES, 'editors'];

const hasAnyRole = (roles?: string[], expected: string[] = []) =>
    Boolean(roles?.some(r => expected.includes(r)));

// ── Item / Section components ────────────────────────────────────────────────

type ItemProps = {
    to: string;
    icon: LucideIcon;
    label: string;
    badge?: React.ReactNode;
    external?: boolean;
};

const SidebarItem: React.FC<ItemProps> = ({ to, icon: Icon, label, badge, external }) => {
    const linkClasses = ({ isActive }: { isActive: boolean }) =>
        cn(
            'group flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm transition-colors',
            'text-muted-foreground hover:bg-accent hover:text-accent-foreground',
            isActive && 'bg-accent text-accent-foreground font-medium',
        );

    const content = (
        <>
            <Icon className="h-4 w-4 shrink-0" aria-hidden />
            <span className="flex-1 truncate">{label}</span>
            {badge}
        </>
    );

    if (external) {
        return (
            <a href={to} className={cn(
                'flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm transition-colors',
                'text-muted-foreground hover:bg-accent hover:text-accent-foreground',
            )}>
                {content}
            </a>
        );
    }

    return (
        <NavLink to={to} end className={linkClasses}>
            {content}
        </NavLink>
    );
};

type SectionProps = {
    title: string;
    children: React.ReactNode;
};

const SidebarSection: React.FC<SectionProps> = ({ title, children }) => (
    <div className="space-y-0.5">
        <h4 className="px-2.5 pb-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/70">
            {title}
        </h4>
        <nav className="flex flex-col gap-0.5">{children}</nav>
    </div>
);

// ── Main component ───────────────────────────────────────────────────────────

export const ProfileSidebar: React.FC<Props> = ({ roles, department, position }) => {
    const { t } = useTranslation();
    const editor = hasAnyRole(roles, EDITOR_ROLES);
    const hrManager = hasAnyRole(roles, HR_ROLES);
    const admin = hasAnyRole(roles, ADMIN_ROLES);
    const hasTasksAccess = hasEmployeeTaskAccessFromParts(roles, department, position);
    const { level, hasHrAccess } = useHRLevel({ enabled: Boolean(roles?.length) });
    const showHrItem = (levels: string[]) => admin || !hasHrAccess || (level ? levels.includes(level) : false);

    return (
        <aside className="bg-card rounded-lg border p-3 space-y-5">
            {/* ── Профиль (user-service) ─────────────────────────────────── */}
            <SidebarSection title={t('profile.sidebar.account')}>
                <SidebarItem to="/myprofile" icon={UserIcon} label={t('profile.sidebar.myProfile')} />
                <SidebarItem to="/settings" icon={Settings} label={t('profile.sidebar.settings')} />
            </SidebarSection>

            {/* ── Коммуникации (messenger + email) ───────────────────────── */}
            <SidebarSection title={t('profile.sidebar.sectionCommunications', 'Коммуникации')}>
                <SidebarItem to="/messenger" icon={MessageSquare} label={t('profile.sidebar.messenger', 'Мессенджер')} />
                <SidebarItem to="/conference" icon={Video} label={t('profile.sidebar.conference', 'Видеоконференция')} />
                <SidebarItem to="/email" icon={Mail} label={t('profile.sidebar.email', 'Почта')} />
            </SidebarSection>

            {/* ── Работа (task + media) ──────────────────────────────────── */}
            <SidebarSection title={t('profile.sidebar.sectionWork', 'Работа')}>
                <SidebarItem to="/calendar" icon={Calendar} label={t('profile.sidebar.calendar', 'Календарь')} />
                <SidebarItem to="/files" icon={FolderClosed} label={t('profile.sidebar.departmentFiles', 'Файлы отдела')} />
                {hasTasksAccess && (
                    <>
                        <SidebarItem to="/tasks" icon={CheckSquare} label={t('tasks.nav.tasks')} />
                        <SidebarItem to="/tasks/roadmap" icon={MapIcon} label={t('tasks.nav.roadmap')} />
                        <SidebarItem to="/tasks/reports" icon={BarChart3} label={t('tasks.nav.reports')} />
                    </>
                )}
                <SidebarItem to="/requests" icon={ClipboardList} label={t('profile.sidebar.requests', 'Запросы')} />
            </SidebarSection>

            {/* ── Контент (cms-service) ──────────────────────────────────── */}
            {editor && (
                <SidebarSection title={t('profile.sidebar.editor')}>
                    <SidebarItem to="/manage/news" icon={Newspaper} label={t('profile.sidebar.manageNews')} />
                    <SidebarItem to="/manage/projects" icon={Layers} label={t('profile.sidebar.manageProjects')} />
                    <SidebarItem
                        to="/manage/contacts"
                        icon={Inbox}
                        label={t('profile.sidebar.contactRequests')}
                        badge={<UnreadContactsBadge />}
                    />
                </SidebarSection>
            )}

            {/* ── HR (hr-service) ────────────────────────────────────────── */}
            {(hrManager || hasHrAccess) && (
                <SidebarSection title={t('profile.sidebar.hrManagement')}>
                    {showHrItem(['junior', 'middle', 'senior', 'lead']) && <SidebarItem to="/hr/employees" icon={Users} label={t('hr.nav.employees')} />}
                    {showHrItem(['middle', 'senior', 'lead']) && <SidebarItem to="/hr/departments" icon={Building2} label={t('hr.nav.structure')} />}
                    {showHrItem(['middle', 'senior', 'lead']) && <SidebarItem to="/hr/positions" icon={Briefcase} label={t('hr.nav.positions')} />}
                    {showHrItem(['lead']) && <SidebarItem to="/admin/levels" icon={SlidersHorizontal} label={t('hr.nav.levels')} />}
                    {showHrItem(['junior', 'middle', 'senior', 'lead']) && <SidebarItem to="/hr/org-chart" icon={Network} label={t('hr.nav.orgChart')} />}
                    {showHrItem(['senior', 'lead']) && <SidebarItem to="/hr/pmo" icon={Handshake} label={t('hr.nav.pmo')} />}
                    {showHrItem(['senior', 'lead']) && <SidebarItem to="/hr/share-links" icon={Link2} label={t('hr.nav.shareLinks')} />}
                    {showHrItem(['middle', 'senior', 'lead']) && <SidebarItem to="/hr/time-tracking" icon={Clock} label={t('hr.nav.timeTracking')} />}
                    {showHrItem(['middle', 'senior', 'lead']) && <SidebarItem to="/hr/recruitment" icon={ClipboardList} label={t('hr.nav.recruitment')} />}
                    {showHrItem(['senior', 'lead']) && <SidebarItem to="/hr/archive" icon={Archive} label={t('hr.nav.archive')} />}
                    {showHrItem(['junior', 'middle', 'senior', 'lead']) && <SidebarItem to="/hr/documents" icon={FileText} label={t('hr.nav.documents')} />}
                    {showHrItem(['senior', 'lead']) && <SidebarItem to="/hr/history" icon={History} label={t('hr.nav.history')} />}
                    {showHrItem(['lead']) && <SidebarItem to="/hr/accounts" icon={KeyRound} label={t('hr.nav.accounts')} />}
                </SidebarSection>
            )}

            {/* ── Администрирование (user/messenger admin + sqladmin) ───── */}
            {admin && (
                <SidebarSection title={t('profile.sidebar.adminTools')}>
                    <SidebarItem to="/admin/users" icon={UserCog} label={t('profile.sidebar.manageUsers', 'Управление пользователями')} />
                    <SidebarItem
                        to="/admin/registrations"
                        icon={UserPlus}
                        label={t('profile.sidebar.registrations')}
                        badge={<PendingRegistrationsBadge />}
                    />
                    <SidebarItem to="/admin/chats" icon={MessagesSquare} label={t('profile.sidebar.manageChats', 'Управление чатами')} />
                    <SidebarItem to="/admin/mailboxes" icon={MailIcon} label={t('profile.sidebar.manageMailboxes', 'Корпоративные ящики')} />
                    <SidebarItem to="/admin/infrastructure" icon={ServerCog} label={t('profile.sidebar.infrastructure', 'Инфраструктура')} />
                </SidebarSection>
            )}

            {/* ── Мониторинг (Grafana + Prometheus) ───────────────────── */}
            {admin && (
                <SidebarSection title={t('profile.sidebar.monitoring', 'Мониторинг')}>
                    <SidebarItem
                        to={grafanaSsoUrl()}
                        icon={Activity}
                        label="Grafana"
                        badge={<ExternalLink className="h-3 w-3 text-muted-foreground" />}
                        external
                    />
                    <SidebarItem
                        to="/prometheus"
                        icon={BarChart3}
                        label="Prometheus"
                        badge={<ExternalLink className="h-3 w-3 text-muted-foreground" />}
                        external
                    />
                </SidebarSection>
            )}
        </aside>
    );
};

export default ProfileSidebar;

// ── Badges ───────────────────────────────────────────────────────────────────

const UnreadContactsBadge: React.FC = () => {
    const { data, error } = useQuery({
        queryKey: ['contact-requests-stats'],
        queryFn: async () => {
            const res = await api.get(apiPath('cms', 'contact-requests/stats/'));
            return res.data;
        },
        retry: false,
        refetchInterval: 30000,
    });

    if (error) return null;
    const count = data?.unhandled ?? 0;
    if (!count) return null;
    return <Badge className="ml-auto h-5 px-1.5 text-[10px]">{count}</Badge>;
};

const PendingRegistrationsBadge: React.FC = () => {
    const { data, error } = useQuery({
        queryKey: ['pending-registrations-count'],
        queryFn: async () => {
            const res = await api.get('users/v1/pending-registrations/');
            return res.data;
        },
        retry: false,
        refetchInterval: 30000,
    });

    if (error) return null;
    const count = Array.isArray(data) ? data.length : 0;
    if (!count) return null;
    return <Badge variant="destructive" className="ml-auto h-5 px-1.5 text-[10px]">{count}</Badge>;
};
