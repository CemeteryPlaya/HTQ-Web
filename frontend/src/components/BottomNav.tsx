import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useActiveProfile } from '@/hooks/useActiveProfile';
import { hasEmployeeTaskAccess, isEditor, isHrManager } from '@/lib/auth/roles';
import { bottomNavItems } from '@/app/navigation/navItems';
import { UserCircle } from 'lucide-react';

export const BottomNav = () => {
    const { t } = useTranslation();
    const location = useLocation();
    const { activeProfile, isLoggedIn } = useActiveProfile({
        staleTime: 5 * 60 * 1000, // 5 minutes
    });

    if (!isLoggedIn || !activeProfile) {
        return null;
    }

    // Разделы берём из общего с шапкой списка (app/navigation/navItems) —
    // раньше здесь был свой, и наборы разошлись: тут не было договоров и
    // согласований, в шапке — чатов, почты и файлов.
    const items = bottomNavItems({
        isEditor: isEditor(activeProfile),
        isHr: isHrManager(activeProfile),
        hasTasks: hasEmployeeTaskAccess(activeProfile),
        hasDepartment: Boolean(activeProfile.department),
    });

    // Профиль — не раздел навигации, а точка входа в личный кабинет, поэтому
    // он не в общем списке и всегда стоит первым.
    const navItems = [
        { to: '/myprofile', icon: UserCircle, label: t('profile.title', 'Профиль') },
        ...items.map((item) => ({
            to: item.href,
            icon: item.icon,
            label: t(item.labelKey, item.labelFallback),
        })),
    ];

    return (
        <div className="fixed bottom-0 left-0 right-0 z-50 flex items-center justify-around gap-1 overflow-x-auto bg-background/80 px-2 py-3 backdrop-blur-md border-t shadow-[0_-4px_10px_rgba(0,0,0,0.05)] md:hidden">
            {navItems.map((item) => {
                const active = location.pathname.startsWith(item.to);
                return (
                    <Link
                        key={item.to}
                        to={item.to}
                        className={`flex shrink-0 flex-col items-center gap-1 min-w-[60px] transition-colors ${active ? 'text-primary' : 'text-muted-foreground hover:text-foreground'
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
