import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from "sonner";
import { useTranslation } from 'react-i18next';
import { ArrowRight, IdCard, Share2 } from 'lucide-react';
import api from '../api/client';
import { Header } from '../components/Header';
import { Footer } from '../components/Footer';
import { ProfileHeader } from '../components/profile/ProfileHeader';
import ProfileSidebar from '../components/profile/ProfileSidebar';
import { ProfileForm } from '../components/profile/ProfileForm';
import { CalendarWidget } from '../components/calendar/CalendarWidget';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { EmployeeCardView } from '@/components/hr/EmployeeCardView';
import { ShareEmployeeDialog } from '@/components/hr/ShareEmployeeDialog';
import { fetchMyEmployeeCard, type EmployeeCard } from '@/api/hr';
import { UserProfile, ProfileFormData } from '../types/userProfile';
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

    // HR card — silently absent for users without an Employee row (e.g.
    // admins not registered as HR employees). 404 stops further retries.
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
                // Server expects a filename for multipart parts; provide a stable
                // one since the cropper produces an unnamed Blob.
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

    const handleFormSubmit = (data: ProfileFormData) => {
        const { avatar, ...rest } = data;
        updateProfileMutation.mutate(rest);
    };

    const handleAvatarChange = (file: Blob) => {
        updateProfileMutation.mutate({ avatar: file });
    };

    const handleLogout = async () => {
        clearAuthStorage();

        // Clear axios default header if client exists
        try {
            const client = await (api as any).getClient();
            if (client && client.defaults && client.defaults.headers) {
                delete client.defaults.headers.common['Authorization'];
            }
        } catch (e) {
            // ignore
        }

        // Clear cached profile data
        queryClient.clear();

        // Redirect to login
        navigate('/login');
    };

    if (isLoading && !profile) return <div className="min-h-screen flex items-center justify-center">{t('profile.loading')}</div>;
    if (error && !profile) return <div className="min-h-screen flex items-center justify-center text-red-500">{t('profile.error')}</div>;

    return (
        <div className="min-h-screen bg-background flex flex-col">
            <Header />
            <main className="flex-1 container mx-auto px-4 py-8">
                <h1 className="text-3xl font-bold mb-6">{t('profile.title')}</h1>

                {profile && (
                    <div className="grid grid-cols-1 lg:grid-cols-4 gap-8">
                        <div className="lg:col-span-1">
                            <ProfileSidebar
                                roles={profile.roles}
                                department={profile.department}
                                position={profile.position}
                            />
                        </div>

                        <div className="lg:col-span-3 space-y-6">
                            <ProfileHeader
                                profile={profile}
                                onAvatarChange={handleAvatarChange}
                                onLogout={handleLogout}
                            />

                            <div className="bg-card rounded-3xl border p-6 shadow-sm overflow-hidden">
                                <h3 className="text-xl font-bold mb-4 px-2">{t('hr.calendar.title')}</h3>
                                <CalendarWidget compact initialView="month" />
                            </div>

                            {myHrCard ? (
                                <div className="bg-card rounded-3xl border p-6 shadow-sm overflow-hidden">
                                    <div className="mb-4 flex flex-wrap items-center justify-between gap-3 px-2">
                                        <div className="flex items-center gap-2">
                                            <IdCard className="h-5 w-5 text-muted-foreground" />
                                            <h3 className="text-xl font-bold">Моя HR-карточка</h3>
                                        </div>
                                        <div className="flex gap-2">
                                            <Button
                                                size="sm"
                                                variant="outline"
                                                className="gap-1.5"
                                                onClick={() => setShareCardOpen(true)}
                                            >
                                                <Share2 className="h-4 w-4" />
                                                Поделиться
                                            </Button>
                                            <Button asChild size="sm" className="gap-1.5">
                                                <Link to={`/hr/employees/${myHrCard.id}`}>
                                                    Открыть
                                                    <ArrowRight className="h-4 w-4" />
                                                </Link>
                                            </Button>
                                        </div>
                                    </div>
                                    <EmployeeCardView card={myHrCard} mode="auth" hideHeader />
                                </div>
                            ) : myPmos.length > 0 && (
                                <div className="bg-card rounded-3xl border p-6 shadow-sm overflow-hidden">
                                    <div className="mb-4 flex items-center justify-between gap-3 px-2">
                                        <h3 className="text-xl font-bold">Мои проекты PMO</h3>
                                        <Badge variant={totalPmoAllocation > 100 ? 'destructive' : 'outline'}>
                                            {totalPmoAllocation}%
                                        </Badge>
                                    </div>
                                    <div className="space-y-2">
                                        {myPmos.map((item) => (
                                            <div key={item.pmo_id} className="flex items-center gap-3 rounded-lg border bg-background px-4 py-3">
                                                <div className="min-w-0 flex-1">
                                                    <p className="truncate text-sm font-medium">{item.pmo_name}</p>
                                                    <p className="truncate text-xs text-muted-foreground">
                                                        {item.pmo_code} · {item.position_in_pmo || item.membership_type}
                                                    </p>
                                                </div>
                                                {item.is_primary && <Badge variant="outline">Лид</Badge>}
                                                <span className="font-mono text-sm tabular-nums">{item.allocation_percent}%</span>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}

                        </div>
                    </div>
                )}
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
