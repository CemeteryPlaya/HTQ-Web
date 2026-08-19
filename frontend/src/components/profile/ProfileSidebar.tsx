import React, { useEffect, useMemo, useRef, useState } from 'react';
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
    UserCog,
    UserPlus,
    MessagesSquare,
    Mail as MailIcon,
    ServerCog,
    Activity,
    ExternalLink,
    Search,
    X,
    ChevronRight,
    Volume2,
    type LucideIcon,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { SoundSettingsModal } from '@/components/sound/SoundSettingsModal';

import api from '@/api/client';
import { apiPath } from '@/api/endpoints';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { DjangoIcon } from '@/components/icons/DjangoIcon';
import { ServiceUnavailableDialog } from '@/components/ServiceUnavailableDialog';
import { useHRLevel } from '@/hooks/useHRLevel';
import { useServiceStatus } from '@/hooks/useServiceStatus';
import { hasEmployeeTaskAccessFromParts } from '@/lib/auth/roles';
import { grafanaSsoUrl } from '@/lib/monitoring';
import { cn } from '@/lib/utils';

type Props = {
    roles?: string[];
    department?: string;
    position?: string;
};

// ── Role buckets — mirror values returned by user-service
const ADMIN_ROLES = ['admin', 'superuser'];
const STAFF_OR_ADMIN_ROLES = [...ADMIN_ROLES, 'staff'];
const HR_ROLES = [
    ...STAFF_OR_ADMIN_ROLES,
    'hr_manager', 'senior_hr', 'junior_hr', 'senior_manager', 'junior_manager',
];
const EDITOR_ROLES = [...STAFF_OR_ADMIN_ROLES, 'editors'];

const hasAnyRole = (roles?: string[], expected: string[] = []) =>
    Boolean(roles?.some(r => expected.includes(r)));

type IconComponent = LucideIcon | React.FC<React.SVGProps<SVGSVGElement>>;

type ItemConfig = {
    id: string;
    to: string;
    icon: IconComponent;
    label: string;
    badge?: React.ReactNode;
    external?: boolean;
    onClick?: (e: React.MouseEvent<HTMLAnchorElement>) => void;
};

type ItemProps = ItemConfig & {
    searchQuery: string;
};

const SidebarItem: React.FC<ItemProps> = ({ to, icon: Icon, label, badge, external, onClick }) => {
    const linkClasses = ({ isActive }: { isActive: boolean }) =>
        cn(
            'group relative flex min-h-[44px] items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-all duration-150 sm:min-h-0',
            'text-muted-foreground hover:bg-accent/80 hover:text-foreground',
            isActive && 'bg-primary/10 text-primary font-semibold border-l-2 border-primary pl-2.5 shadow-2xs',
        );

    const content = (
        <>
            <Icon className="h-4 w-4 shrink-0 transition-transform duration-200 group-hover:scale-110" aria-hidden />
            <span className="flex-1 truncate">{label}</span>
            {badge}
        </>
    );

    if (external) {
        return (
            <a
                href={to}
                className={cn(
                    'group flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-all duration-150',
                    'text-muted-foreground hover:bg-accent/80 hover:text-foreground',
                )}
                onClick={onClick}
            >
                {content}
            </a>
        );
    }

    return (
        <NavLink to={to} end className={linkClasses} onClick={onClick}>
            {content}
        </NavLink>
    );
};

type SectionProps = {
    id: string;
    title: string;
    children: React.ReactNode;
    count?: number;
    forceOpen?: boolean;
};

const SECTIONS_KEY = 'htq.profileSidebar.collapsedSections';

/**
 * Сайдбар живёт только на /myprofile и /settings, поэтому каждый заход на
 * профиль монтирует его заново. Без сохранённого состояния свёрнутый раздел
 * (в HR — дюжина страниц) схлопывался обратно при каждом возврате, и до своих
 * страниц приходилось докликиваться снова.
 */
function readCollapsedSections(): Record<string, boolean> {
    if (typeof window === 'undefined') return {};
    try {
        const parsed: unknown = JSON.parse(window.localStorage.getItem(SECTIONS_KEY) ?? '{}');
        return parsed && typeof parsed === 'object' ? (parsed as Record<string, boolean>) : {};
    } catch {
        // Битый JSON или запрещённый storage — навигацию это ронять не должно.
        return {};
    }
}

function writeCollapsedSection(id: string, collapsed: boolean) {
    if (typeof window === 'undefined') return;
    try {
        window.localStorage.setItem(
            SECTIONS_KEY,
            JSON.stringify({ ...readCollapsedSections(), [id]: collapsed }),
        );
    } catch {
        // Приватный режим: выбор просто не переживёт перезагрузку страницы.
    }
}

const SidebarSection: React.FC<SectionProps> = ({ id, title, children, count, forceOpen = false }) => {
    // Разделы раскрыты по умолчанию: доступные страницы должны быть видны
    // сразу, а не после догадки, что заголовок вообще кликабелен.
    const [isOpen, setIsOpen] = useState(() => !readCollapsedSections()[id]);
    const containerRef = useRef<HTMLDivElement>(null);
    const revealRef = useRef(false);

    const expanded = forceOpen || isOpen;
    const contentId = `sidebar-section-${id}`;

    const toggle = () => {
        const next = !isOpen;
        revealRef.current = next;
        writeCollapsedSection(id, !next);
        setIsOpen(next);
    };

    // Раздел у нижнего края прокручиваемого сайдбара раскрывался за пределами
    // видимой области — со стороны это выглядело как «клик ничего не сделал».
    useEffect(() => {
        if (!expanded || !revealRef.current) return;
        revealRef.current = false;
        containerRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }, [expanded]);

    return (
        <div ref={containerRef} className="space-y-1">
            <button
                type="button"
                onClick={toggle}
                aria-expanded={expanded}
                aria-controls={contentId}
                className={cn(
                    'flex min-h-[44px] w-full items-center justify-between gap-2 rounded-md px-2.5 py-1.5',
                    'text-xs font-bold uppercase tracking-wider transition-colors sm:min-h-0',
                    // Раскрытое состояние помечено фоном, цветом текста, счётчиком
                    // и поворотом шеврона: по одному шеврону в 14px его не видно.
                    expanded
                        ? 'bg-accent/60 text-foreground'
                        : 'text-muted-foreground/80 hover:bg-accent/40 hover:text-foreground',
                )}
            >
                <span className="truncate">{title}</span>
                <div className="flex items-center gap-1.5 shrink-0">
                    {count !== undefined && count > 0 && (
                        <span
                            className={cn(
                                'rounded-full px-1.5 py-0.5 text-[10px] font-semibold transition-colors',
                                expanded ? 'bg-primary/15 text-primary' : 'bg-muted/80 text-muted-foreground',
                            )}
                        >
                            {count}
                        </span>
                    )}
                    <ChevronRight
                        aria-hidden
                        className={cn(
                            'h-3.5 w-3.5 transition-transform duration-200',
                            expanded ? 'rotate-90 text-primary' : 'text-muted-foreground/70',
                        )}
                    />
                </div>
            </button>
            {expanded && (
                <nav id={contentId} className="flex flex-col gap-0.5 pl-0.5">
                    {children}
                </nav>
            )}
        </div>
    );
};

export const ProfileSidebar: React.FC<Props> = ({ roles, department, position }) => {
    const { t } = useTranslation();
    const [searchQuery, setSearchQuery] = useState('');

    const editor = hasAnyRole(roles, EDITOR_ROLES);
    const hrManager = hasAnyRole(roles, HR_ROLES);
    const admin = hasAnyRole(roles, ADMIN_ROLES);
    const elevated = hasAnyRole(roles, STAFF_OR_ADMIN_ROLES);
    const hasTasksAccess = hasEmployeeTaskAccessFromParts(roles, department, position);
    const { level, hasHrAccess } = useHRLevel({ enabled: Boolean(roles?.length) });
    const showHrItem = (levels: string[]) => admin || !hasHrAccess || (level ? levels.includes(level) : false);

    const { isDisabled } = useServiceStatus();
    const [blockedService, setBlockedService] = useState<string | null>(null);
    const gateService = (service: string) => (e: React.MouseEvent<HTMLAnchorElement>) => {
        if (isDisabled(service)) {
            e.preventDefault();
            setBlockedService(service);
        }
    };

    // Construct section items
    const accountItems: ItemConfig[] = useMemo(() => [
        { id: 'profile', to: '/myprofile', icon: UserIcon, label: t('profile.sidebar.myProfile') },
        { id: 'settings', to: '/settings', icon: Settings, label: t('profile.sidebar.settings') },
    ], [t]);

    const communicationItems: ItemConfig[] = useMemo(() => [
        { id: 'messenger', to: '/messenger', icon: MessageSquare, label: t('profile.sidebar.messenger', 'Мессенджер') },
        { id: 'conference', to: '/conference', icon: Video, label: t('profile.sidebar.conference', 'Видеоконференция'), onClick: gateService('conference') },
        { id: 'conference-history', to: '/conference/history', icon: History, label: t('profile.sidebar.conferenceHistory', 'История конференций'), onClick: gateService('conference') },
        { id: 'email', to: '/email', icon: Mail, label: t('profile.sidebar.email', 'Почта') },
    ], [t]);

    const workItems: ItemConfig[] = useMemo(() => {
        const items: ItemConfig[] = [
            { id: 'calendar', to: '/calendar', icon: Calendar, label: t('profile.sidebar.calendar', 'Календарь') },
            { id: 'files', to: '/files', icon: FolderClosed, label: t('profile.sidebar.departmentFiles', 'Файлы отдела') },
        ];
        if (hasTasksAccess) {
            items.push({ id: 'tasks', to: '/tasks', icon: CheckSquare, label: t('tasks.nav.tasks') });
        }
        if (hasTasksAccess && elevated) {
            items.push(
                { id: 'roadmap', to: '/tasks/roadmap', icon: MapIcon, label: t('tasks.nav.roadmap') },
                { id: 'manage-projects', to: '/manage/projects', icon: Layers, label: t('tasks.nav.projects', 'Проекты') },
                { id: 'reports', to: '/tasks/reports', icon: BarChart3, label: t('tasks.nav.reports') },
            );
        }
        items.push({ id: 'requests', to: '/requests', icon: ClipboardList, label: t('profile.sidebar.requests', 'Запросы') });
        return items;
    }, [t, hasTasksAccess, elevated]);

    const contentItems: ItemConfig[] = useMemo(() => {
        if (!editor) return [];
        return [
            { id: 'news', to: '/manage/news', icon: Newspaper, label: t('profile.sidebar.manageNews') },
            { id: 'contacts', to: '/manage/contacts', icon: Inbox, label: t('profile.sidebar.contactRequests'), badge: <UnreadContactsBadge /> },
        ];
    }, [t, editor]);

    const hrItems: ItemConfig[] = useMemo(() => {
        if (!hrManager && !hasHrAccess) return [];
        const items: ItemConfig[] = [];
        if (showHrItem(['junior', 'middle', 'senior', 'lead'])) items.push({ id: 'hr-employees', to: '/hr/employees', icon: Users, label: t('hr.nav.employees') });
        if (showHrItem(['middle', 'senior', 'lead'])) items.push({ id: 'hr-departments', to: '/hr/departments', icon: Building2, label: t('hr.nav.structure') });
        if (showHrItem(['middle', 'senior', 'lead'])) items.push({ id: 'hr-positions', to: '/hr/positions', icon: Briefcase, label: t('hr.nav.positions') });
        if (showHrItem(['junior', 'middle', 'senior', 'lead'])) items.push({ id: 'hr-org', to: '/hr/org-chart', icon: Network, label: t('hr.nav.orgChart') });
        if (showHrItem(['senior', 'lead'])) items.push({ id: 'hr-pmo', to: '/hr/pmo', icon: Handshake, label: t('hr.nav.pmo') });
        if (showHrItem(['senior', 'lead'])) items.push({ id: 'hr-share', to: '/hr/share-links', icon: Link2, label: t('hr.nav.shareLinks') });
        if (showHrItem(['middle', 'senior', 'lead'])) items.push({ id: 'hr-time', to: '/hr/time-tracking', icon: Clock, label: t('hr.nav.timeTracking') });
        if (showHrItem(['middle', 'senior', 'lead'])) items.push({ id: 'hr-recruitment', to: '/hr/recruitment', icon: ClipboardList, label: t('hr.nav.recruitment') });
        if (showHrItem(['senior', 'lead'])) items.push({ id: 'hr-archive', to: '/hr/archive', icon: Archive, label: t('hr.nav.archive') });
        if (showHrItem(['junior', 'middle', 'senior', 'lead'])) items.push({ id: 'hr-docs', to: '/hr/documents', icon: FileText, label: t('hr.nav.documents') });
        if (showHrItem(['senior', 'lead'])) items.push({ id: 'hr-history', to: '/hr/history', icon: History, label: t('hr.nav.history') });
        if (showHrItem(['lead'])) items.push({ id: 'hr-accounts', to: '/hr/accounts', icon: KeyRound, label: t('hr.nav.accounts') });
        return items;
    }, [t, hrManager, hasHrAccess, admin, level]);

    const adminItems: ItemConfig[] = useMemo(() => {
        if (!admin) return [];
        return [
            { id: 'admin-users', to: '/admin/users', icon: UserCog, label: t('profile.sidebar.manageUsers', 'Управление пользователями') },
            { id: 'admin-registrations', to: '/admin/registrations', icon: UserPlus, label: t('profile.sidebar.registrations'), badge: <PendingRegistrationsBadge /> },
            { id: 'admin-chats', to: '/admin/chats', icon: MessagesSquare, label: t('profile.sidebar.manageChats', 'Управление чатами') },
            { id: 'admin-mailboxes', to: '/admin/mailboxes', icon: MailIcon, label: t('profile.sidebar.manageMailboxes', 'Корпоративные ящики') },
            { id: 'admin-infra', to: '/admin/infrastructure', icon: ServerCog, label: t('profile.sidebar.infrastructure', 'Инфраструктура') },
            {
                id: 'admin-django',
                to: '/django-admin/',
                icon: DjangoIcon,
                label: t('profile.sidebar.djangoAdmin', 'Админка Django'),
                badge: <ExternalLink className="h-3 w-3 text-muted-foreground" />,
                external: true,
            },
        ];
    }, [t, admin]);

    const monitoringItems: ItemConfig[] = useMemo(() => {
        if (!admin) return [];
        return [
            { id: 'grafana', to: grafanaSsoUrl(), icon: Activity, label: 'Grafana', badge: <ExternalLink className="h-3 w-3 text-muted-foreground" />, external: true },
            { id: 'prometheus', to: '/prometheus', icon: BarChart3, label: 'Prometheus', badge: <ExternalLink className="h-3 w-3 text-muted-foreground" />, external: true },
        ];
    }, [admin]);

    // Filtering logic
    const filterFn = (items: ItemConfig[]) => {
        if (!searchQuery.trim()) return items;
        const q = searchQuery.toLowerCase();
        return items.filter(item => item.label.toLowerCase().includes(q));
    };

    const filteredAccount = filterFn(accountItems);
    const filteredComm = filterFn(communicationItems);
    const filteredWork = filterFn(workItems);
    const filteredContent = filterFn(contentItems);
    const filteredHr = filterFn(hrItems);
    const filteredAdmin = filterFn(adminItems);
    const filteredMonitoring = filterFn(monitoringItems);

    const totalResults = filteredAccount.length + filteredComm.length + filteredWork.length +
        filteredContent.length + filteredHr.length + filteredAdmin.length + filteredMonitoring.length;

    const isSearching = Boolean(searchQuery.trim());

    return (
        <aside className="sticky top-20 max-h-[calc(100vh-6rem)] overflow-y-auto rounded-2xl border bg-card p-3 shadow-xs space-y-4 scrollbar-thin">
            {/* Quick Search */}
            <div className="relative">
                <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground pointer-events-none" />
                <Input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder={t('common.search', 'Поиск по меню...')}
                    className="h-8.5 pl-8 pr-7 text-xs bg-muted/40 border-muted focus-visible:bg-background rounded-lg transition-colors"
                />
                {searchQuery && (
                    <button
                        type="button"
                        onClick={() => setSearchQuery('')}
                        className="absolute right-2 top-2 text-muted-foreground hover:text-foreground p-0.5 rounded-sm"
                    >
                        <X className="h-3.5 w-3.5" />
                    </button>
                )}
            </div>

            {isSearching && totalResults === 0 && (
                <div className="py-6 text-center text-xs text-muted-foreground">
                    Ничего не найдено
                </div>
            )}

            {/* Account Section */}
            {filteredAccount.length > 0 && (
                <SidebarSection id="account" title={t('profile.sidebar.account')} count={filteredAccount.length} forceOpen={isSearching}>
                    {filteredAccount.map((item) => (
                        <SidebarItem key={item.id} {...item} searchQuery={searchQuery} />
                    ))}
                </SidebarSection>
            )}

            {/* Communications Section */}
            {filteredComm.length > 0 && (
                <SidebarSection id="communications" title={t('profile.sidebar.sectionCommunications', 'Коммуникации')} count={filteredComm.length} forceOpen={isSearching}>
                    {filteredComm.map((item) => (
                        <SidebarItem key={item.id} {...item} searchQuery={searchQuery} />
                    ))}
                </SidebarSection>
            )}

            {/* Work Section */}
            {filteredWork.length > 0 && (
                <SidebarSection id="work" title={t('profile.sidebar.sectionWork', 'Работа')} count={filteredWork.length} forceOpen={isSearching}>
                    {filteredWork.map((item) => (
                        <SidebarItem key={item.id} {...item} searchQuery={searchQuery} />
                    ))}
                </SidebarSection>
            )}

            {/* Content Section */}
            {filteredContent.length > 0 && (
                <SidebarSection id="content" title={t('profile.sidebar.editor')} count={filteredContent.length} forceOpen={isSearching}>
                    {filteredContent.map((item) => (
                        <SidebarItem key={item.id} {...item} searchQuery={searchQuery} />
                    ))}
                </SidebarSection>
            )}

            {/* HR Section */}
            {filteredHr.length > 0 && (
                <SidebarSection id="hr" title={t('profile.sidebar.hrManagement')} count={filteredHr.length} forceOpen={isSearching}>
                    {filteredHr.map((item) => (
                        <SidebarItem key={item.id} {...item} searchQuery={searchQuery} />
                    ))}
                </SidebarSection>
            )}

            {/* Admin Section */}
            {filteredAdmin.length > 0 && (
                <SidebarSection id="admin" title={t('profile.sidebar.adminTools')} count={filteredAdmin.length} forceOpen={isSearching}>
                    {filteredAdmin.map((item) => (
                        <SidebarItem key={item.id} {...item} searchQuery={searchQuery} />
                    ))}
                </SidebarSection>
            )}

            {/* Monitoring Section */}
            {filteredMonitoring.length > 0 && (
                <SidebarSection id="monitoring" title={t('profile.sidebar.monitoring', 'Мониторинг')} count={filteredMonitoring.length} forceOpen={isSearching}>
                    {filteredMonitoring.map((item) => (
                        <SidebarItem key={item.id} {...item} searchQuery={searchQuery} />
                    ))}
                </SidebarSection>
            )}

            {/* Quick sound control */}
            <div className="pt-2 mt-auto border-t border-border/40">
                <SoundSettingsModal
                    trigger={
                        <button
                            type="button"
                            className="group flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium text-muted-foreground hover:bg-accent/80 hover:text-foreground transition-all duration-150"
                        >
                            <Volume2 className="h-4 w-4 shrink-0 transition-transform duration-200 group-hover:scale-110" />
                            <span className="flex-1 truncate text-left">Звуки уведомлений</span>
                        </button>
                    }
                />
            </div>

            {blockedService && (
                <ServiceUnavailableDialog
                    service={blockedService}
                    open={Boolean(blockedService)}
                    onOpenChange={(open) => {
                        if (!open) setBlockedService(null);
                    }}
                />
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
    return <Badge className="ml-auto h-5 px-1.5 text-[10px] bg-primary text-primary-foreground">{count}</Badge>;
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
    return <Badge variant="destructive" className="ml-auto h-5 px-1.5 text-[10px] animate-pulse">{count}</Badge>;
};
