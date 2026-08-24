import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from "sonner";
import { useTranslation } from 'react-i18next';
import { ArrowRight, IdCard, Share2, Calendar as CalendarIcon, FolderGit2 } from 'lucide-react';
import api from '../api/client';
import { Header } from '../components/Header';
import { Footer } from '../components/Footer';
import { ProfileHeader } from '../components/profile/ProfileHeader';
import ProfileSidebar from '../components/profile/ProfileSidebar';
import { ConnectCorporateMailbox } from '@/components/mail/ConnectCorporateMailbox';
import { CalendarWidget } from '../components/calendar/CalendarWidget';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { EmployeeCardView } from '@/components/hr/EmployeeCardView';
import { ShareEmployeeDialog } from '@/components/hr/ShareEmployeeDialog';
import { fetchMyEmployeeCard, type EmployeeCard } from '@/api/hr';
import { UserProfile } from '../types/userProfile';
import {
    clearAuthStorage,
    readCachedProfile,
    writeCachedProfile,
} from '@/lib/auth/profileStorage';

interface EmployeePmo {
    pmo_id: number;
    pmo_name: string;
    pmo_code: string;
    membership_type: string;
    position_in_pmo: string | null;
    allocation_percent: number;
    is_primary: boolean;
}

const MyProfile = () => {
    const { t } = useTranslation();
    const queryClient = useQueryClient();
    const navigate = useNavigate();

    const { data: serverProfile, isLoading, error } = useQuery({
        queryKey: ['profile'],
        queryFn: async () => {
            const res = await api.get<UserProfile>('users/v1/profile/me');
            writeCachedProfile(res.data);
            return res.data;
        }
    });

    const profile = serverProfile || readCachedProfile();

    const { data: myPmos = [] } = useQuery<EmployeePmo[]>({
        queryKey: ['my-pmos'],
        queryFn: async () => (await api.get<EmployeePmo[]>('hr/v1/employees/me/pmos')).data,
        retry: false,
        enabled: Boolean(profile),
    });

    const totalPmoAllocation = myPmos.reduce((sum, item) => sum + item.allocation_percent, 0);

    const { data: myHrCard } = useQuery<EmployeeCard>({
        queryKey: ['my-hr-card'],
        queryFn: fetchMyEmployeeCard,
        retry: false,
        enabled: Boolean(profile),
    });

    const [shareCardOpen, setShareCardOpen] = useState(false);

    const updateProfileMutation = useMutation({
        mutationFn: async (data: Partial<UserProfile> & { avatar?: Blob }) => {
            const formData = new FormData();

            if (data.display_name !== undefined) formData.append('display_name', data.display_name);
            if (data.firstName !== undefined) formData.append('firstName', data.firstName);
            if (data.lastName !== undefined) formData.append('lastName', data.lastName);
            if (data.patronymic !== undefined) formData.append('patronymic', data.patronymic);
            if (data.phone !== undefined) formData.append('phone', data.phone);
            if (data.bio !== undefined) formData.append('bio', data.bio);
            if (data.settings) formData.append('settings', JSON.stringify(data.settings));
            if (data.avatar) {
                const filename = data.avatar instanceof File ? data.avatar.name : 'avatar.jpg';
                formData.append('avatar', data.avatar, filename);
            }

            const res = await api.patch<UserProfile>('users/v1/profile/me', formData, {
                headers: { 'Content-Type': 'multipart/form-data' }
            });
            return res.data;
        },
        onSuccess: (updatedProfile) => {
            queryClient.setQueryData(['profile'], updatedProfile);
            toast.success(t('profile.updated'));
        },
        onError: (err) => {
            console.error(err);
            toast.error("Failed to update profile");
        }
    });

    const handleAvatarChange = (file: Blob) => {
        updateProfileMutation.mutate({ avatar: file });
    };

    const handleLogout = async () => {
        clearAuthStorage();
        try {
            const client = await (api as any).getClient();
            if (client && client.defaults && client.defaults.headers) {
                delete client.defaults.headers.common['Authorization'];
            }
        } catch (e) {
            // ignore
        }
        queryClient.clear();
        navigate('/login');
    };

    if (isLoading && !profile) {
        return (
            <div className="min-h-screen bg-background flex flex-col">
                <Header />
                <main className="flex-1 container mx-auto px-4 py-16 flex items-center justify-center">
                    <div className="flex items-center gap-3 text-muted-foreground animate-pulse">
                        <div className="h-5 w-5 rounded-full border-2 border-primary border-t-transparent animate-spin" />
                        <span className="font-medium text-sm">{t('profile.loading', 'Загрузка профиля...')}</span>
                    </div>
                </main>
                <Footer />
            </div>
        );
    }

    if (error && !profile) {
        return (
            <div className="min-h-screen bg-background flex flex-col">
                <Header />
                <main className="flex-1 container mx-auto px-4 py-16 flex items-center justify-center">
                    <div className="text-center space-y-3">
                        <p className="text-destructive font-medium">{t('profile.error', 'Ошибка загрузки профиля')}</p>
                        <Button variant="outline" size="sm" onClick={() => window.location.reload()}>
                            {t('common.refreshPage')}
                        </Button>
                    </div>
                </main>
                <Footer />
            </div>
        );
    }

    return (
        <div className="min-h-screen bg-background flex flex-col">
            <Header />

            <main className="flex-1 mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
                {/* Одна сетка на всю страницу.
                    Телефон: одна колонка, порядок задаётся order-*.
                    Десктоп: ряд и колонка КАЖДОГО блока заданы явно
                    (lg:row-start-* + lg:col-start-*).

                    Явно — потому что неявная расстановка по order-* ставила
                    шапку профиля в один ряд с сайдбаром: высота ряда равнялась
                    высоте сайдбара, под короткой шапкой зияла пустота на весь
                    его рост, а контент начинался только НИЖЕ сайдбара.
                    Сайдбар растянут на два ряда (lg:row-span-2) — тогда справа
                    от него шапка и контент идут друг за другом. */}
                <div className="grid grid-cols-1 lg:grid-cols-12 gap-x-8 gap-y-6 items-start">
                    {/* Profile Hero Header — на мобильном в самом верху: профиль
                        должен открываться на имени и аватаре, а не на заголовке. */}
                    {profile && (
                        <div className="order-1 lg:col-span-9 lg:col-start-4 lg:row-start-2">
                            <ProfileHeader
                                profile={profile}
                                onAvatarChange={handleAvatarChange}
                                onLogout={handleLogout}
                            />
                        </div>
                    )}

                    {/* Page Title Header */}
                    <div className="order-2 flex items-center justify-between lg:col-span-12 lg:row-start-1">
                        <div>
                            <h1 className="text-2xl sm:text-3xl font-extrabold tracking-tight">{t('profile.title', 'Мой профиль')}</h1>
                            <p className="text-xs text-muted-foreground mt-0.5">
                                {t('profile.pageSubtitle')}
                            </p>
                        </div>
                    </div>

                    {profile && (
                        <>
                        {/* Main Content Area */}
                        <div className="order-3 lg:col-span-9 lg:col-start-4 lg:row-start-3 space-y-6">
                            {/* Корпоративная почта — блок сам скрывается,
                                если админ не включил самоподключение. */}
                            <ConnectCorporateMailbox />

                            {/* Calendar Widget Card */}
                            <div className="bg-card rounded-3xl border p-6 shadow-2xs hover:shadow-xs transition-all">
                                <div className="mb-4 flex items-center gap-2 px-1">
                                    <CalendarIcon className="h-5 w-5 text-primary" />
                                    <h3 className="text-lg font-bold">{t('hr.calendar.title', 'Календарь')}</h3>
                                </div>
                                <CalendarWidget compact initialView="month" />
                            </div>

                            {/* HR Card Block */}
                            {myHrCard ? (
                                <div className="bg-card rounded-3xl border p-6 shadow-2xs hover:shadow-xs transition-all overflow-hidden">
                                    <div className="mb-4 flex flex-wrap items-center justify-between gap-3 px-1">
                                        <div className="flex items-center gap-2">
                                            <IdCard className="h-5 w-5 text-primary" />
                                            <h3 className="text-lg font-bold">{t('profile.hrCard')}</h3>
                                        </div>
                                        <div className="flex gap-2">
                                            <Button
                                                size="sm"
                                                variant="outline"
                                                className="gap-1.5 rounded-xl"
                                                onClick={() => setShareCardOpen(true)}
                                            >
                                                <Share2 className="h-4 w-4" />
                                                {t('common.share')}
                                            </Button>
                                            <Button asChild size="sm" className="gap-1.5 rounded-xl">
                                                <Link to="/employee/me">
                                                    {t('common.open')}
                                                    <ArrowRight className="h-4 w-4" />
                                                </Link>
                                            </Button>
                                        </div>
                                    </div>
                                    <EmployeeCardView card={myHrCard} mode="auth" hideHeader />
                                </div>
                            ) : myPmos.length > 0 && (
                                <div className="bg-card rounded-3xl border p-6 shadow-2xs hover:shadow-xs transition-all overflow-hidden">
                                    <div className="mb-4 flex items-center justify-between gap-3 px-1">
                                        <div className="flex items-center gap-2">
                                            <FolderGit2 className="h-5 w-5 text-primary" />
                                            <h3 className="text-lg font-bold">{t('profile.myPmoProjects')}</h3>
                                        </div>
                                        <Badge variant={totalPmoAllocation > 100 ? 'destructive' : 'outline'}>
                                            {t('profile.pmoAllocation', { percent: totalPmoAllocation })}
                                        </Badge>
                                    </div>
                                    <div className="space-y-2.5">
                                        {myPmos.map((item) => (
                                            <div
                                                key={item.pmo_id}
                                                className="flex items-center gap-4 rounded-xl border bg-muted/30 hover:bg-muted/50 px-4 py-3.5 transition-colors"
                                            >
                                                <div className="min-w-0 flex-1">
                                                    <p className="truncate text-sm font-semibold">{item.pmo_name}</p>
                                                    <p className="truncate text-xs text-muted-foreground mt-0.5">
                                                        {item.pmo_code} · {item.position_in_pmo || item.membership_type}
                                                    </p>
                                                </div>
                                                {item.is_primary && (
                                                    <Badge variant="secondary" className="text-[11px]">
                                                        {t('profile.pmoLead')}
                                                    </Badge>
                                                )}
                                                <span className="font-mono text-sm font-semibold tabular-nums text-foreground">
                                                    {item.allocation_percent}%
                                                </span>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}
                        </div>

                        {/* Sidebar (последним на мобильном, левая колонка на десктопе) */}
                        <div className="order-4 lg:col-span-3 lg:col-start-1 lg:row-start-2 lg:row-span-2">
                            <ProfileSidebar
                                roles={profile.roles}
                                department={profile.department}
                                position={profile.position}
                            />
                        </div>
                        </>
                    )}
                </div>
            </main>

            <ShareEmployeeDialog
                open={shareCardOpen}
                employee={myHrCard ? { id: myHrCard.id, full_name: myHrCard.full_name } : null}
                onClose={() => setShareCardOpen(false)}
            />

            <Footer />
        </div>
    );
};

export default MyProfile;
