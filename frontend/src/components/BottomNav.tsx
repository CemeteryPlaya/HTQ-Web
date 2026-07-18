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
        <div className="fixed bottom-0 left-0 right-0 z-50 flex items-center justify-around bg-background/80 px-2 py-3 backdrop-blur-md border-t shadow-[0_-4px_10px_rgba(0,0,0,0.05)] md:hidden">
            {navItems.map((item) => {
                const active = location.pathname.startsWith(item.to);
                return (
                    <Link
                        key={item.to}
                        to={item.to}
                        className={`flex flex-col items-center gap-1 min-w-[64px] transition-colors ${active ? 'text-primary' : 'text-muted-foreground hover:text-foreground'
                            }`}
                    >
                        <item.icon className={`h-5 w-5 ${active ? 'fill-primary/20' : ''}`} />
                        <span className="text-[10px] font-medium leading-none">{item.label}</span>
                    </Link>
                );
            })}
        </div>
    );
};
