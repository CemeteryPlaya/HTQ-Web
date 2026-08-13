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
