import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useActiveProfile } from '@/hooks/useActiveProfile';
import { hasEmployeeTaskAccess, isEditor, isHrManager } from '@/lib/auth/roles';
import {
    CheckSquare,
    Users,
    FileText,
    UserCircle,
    MessageCircle,
    Mail,
    Calendar,
    FolderOpen,
} from 'lucide-react';

export const BottomNav = () => {
    const { t } = useTranslation();
    const location = useLocation();
    const { activeProfile, isLoggedIn } = useActiveProfile({
        staleTime: 5 * 60 * 1000, // 5 minutes
    });

    if (!isLoggedIn || !activeProfile) {
        return null;
    }

    // Role definitions
    const hasEditorAccess = isEditor(activeProfile);
    const hasHrAccess = isHrManager(activeProfile);
    const hasTasksAccess = hasEmployeeTaskAccess(activeProfile);

    const navItems = [];

    // Everyone gets Profile/Home
    navItems.push({
        to: '/myprofile',
        icon: UserCircle,
        label: t('profile.title') || 'Профиль',
    });

    // Everyone gets Messenger
    navItems.push({
        to: '/messenger',
        icon: MessageCircle,
        label: 'Чаты',
    });

    // Everyone gets Email
    navItems.push({
        to: '/email',
        icon: Mail,
        label: 'Почта',
    });

    // Everyone gets Calendar
    navItems.push({
        to: '/calendar',
        icon: Calendar,
        label: 'Календарь',
    });

    // Files — accessible to employees with a department
    if (activeProfile.department) {
        navItems.push({
            to: '/files',
            icon: FolderOpen,
            label: 'Файлы',
        });
    }

    // Editor / News access
    if (hasEditorAccess) {
        navItems.push({
            to: '/manage/news',
            icon: FileText,
            label: t('header.news') || 'Новости',
        });
    }

    // HR Access
    if (hasHrAccess) {
        navItems.push({
            to: '/hr/employees',
            icon: Users,
            label: t('profile.sidebar.employees') || 'Сотрудники',
        });
    }

    // Tasks Access
    if (hasTasksAccess) {
        navItems.push({
            to: '/tasks',
            icon: CheckSquare,
            label: t('profile.sidebar.tasks') || 'Задачи',
        });
    }

    return (
        <>
            {/* Распорка в обычном потоке. BottomNav смонтирован в App.tsx сразу
                после <AppRoutes/>, поэтому этот блок оказывается в самом конце
                документа и резервирует место под фиксированную панель. Без него
                каждая страница обязана была бы помнить про собственный pb-24 —
                и любая забывшая прятала под панелью низ футера или кнопку. */}
            <div
                aria-hidden="true"
                className="md:hidden"
                style={{ height: 'calc(4.25rem + env(safe-area-inset-bottom, 0px))' }}
            />
            <div className="fixed bottom-0 left-0 right-0 z-50 flex items-center justify-around bg-background/95 px-1 py-1.5 pb-safe backdrop-blur-lg border-t border-border/60 shadow-[0_-4px_12px_rgba(0,0,0,0.08)] md:hidden">
            {navItems.map((item) => {
                const active = location.pathname.startsWith(item.to);
                return (
                    <Link
                        key={item.to}
                        to={item.to}
                        className={`flex flex-col items-center justify-center gap-1 min-w-[48px] min-h-[44px] px-1 py-1 rounded-xl transition-all active:scale-95 ${
                            active ? 'text-primary font-bold' : 'text-muted-foreground hover:text-foreground'
                        }`}
                    >
                        <div className={`p-1 rounded-xl transition-colors ${active ? 'bg-primary/15 text-primary' : ''}`}>
                            <item.icon className={`h-5 w-5 ${active ? 'fill-primary/20 stroke-[2.5]' : ''}`} />
                        </div>
                        <span className="text-[10px] font-medium leading-none text-center">{item.label}</span>
                    </Link>
                );
            })}
            </div>
        </>
    );
};
