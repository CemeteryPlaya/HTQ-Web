import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useTranslation } from 'react-i18next';
import i18n from '@/i18n';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import {
    Briefcase,
    Building2,
    CalendarDays,
    KeyRound,
    LogOut,
    Mail,
    Phone,
    ShieldCheck,
    UserCircle } from 'lucide-react';

import api from '@/api/client';
import { BackToProfile } from '@/components/BackToProfile';
import { CorporateMailSettings } from '@/components/mail/CorporateMailSettings';
import { Header } from '@/components/Header';
import { Footer } from '@/components/Footer';
import ProfileSidebar from '@/components/profile/ProfileSidebar';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { PhoneInput, isKzPhoneValid } from '@/components/ui/phone-input';
import {
    Form,
    FormControl,
    FormDescription,
    FormField,
    FormItem,
    FormLabel,
    FormMessage,
} from '@/components/ui/form';
import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
} from '@/components/ui/card';
import { Separator } from '@/components/ui/separator';
import { Textarea } from '@/components/ui/textarea';
import { UserProfile } from '@/types/userProfile';
import {
    clearAuthStorage,
    readCachedProfile,
    writeCachedProfile,
} from '@/lib/auth/profileStorage';

// ── Backend contract ─────────────────────────────────────────────────────────
// PATCH /api/users/v1/profile/me  — phone + settings (JSON, replaces whole obj).
//   Secondary email lives in settings.secondary_email (no schema change).
// POST  /api/users/v1/profile/change-password  — { current_password, new_password }.
// ─────────────────────────────────────────────────────────────────────────────

const Settings: React.FC = () => {
    const { t } = useTranslation();
    const navigate = useNavigate();
    const queryClient = useQueryClient();

    const { data: serverProfile, isLoading } = useQuery({
        queryKey: ['profile'],
        queryFn: async () => {
            const res = await api.get<UserProfile>('users/v1/profile/me');
            writeCachedProfile(res.data);
            return res.data;
        },
    });

    const profile = serverProfile || readCachedProfile();

    if (isLoading && !profile) {
        return (
            <div className="min-h-screen flex items-center justify-center">
                {t('profile.loading')}
            </div>
        );
    }

    if (!profile) {
        return (
            <div className="min-h-screen flex items-center justify-center text-red-500">
                {t('profile.error')}
            </div>
        );
    }

    return (
        <div className="min-h-screen bg-background flex flex-col">
            <Header />
            <main className="flex-1 container mx-auto px-4 py-6 sm:px-6 lg:px-8">
                <div className="flex items-center gap-3 mb-6">
                    <BackToProfile className="mb-0 text-xs" />
                    <h1 className="text-2xl sm:text-3xl font-bold">
                        {t('settingsPage.title', 'Настройки')}
                    </h1>
                </div>

                <div className="grid grid-cols-1 lg:grid-cols-4 gap-8 items-start">
                    {/* Settings cards (renders FIRST on mobile) */}
                    <div className="order-1 lg:order-2 lg:col-span-3 space-y-6">
                        <PersonalInfoCard profile={profile} />
                        <ContactInfoCard profile={profile} />
                        <WorkInfoCard />
                        <PasswordCard />
                        <AccountCard
                            email={profile.email}
                            onLogout={async () => {
                                clearAuthStorage();
                                try {
                                    const client = await api.getClient();
                                    if (client?.defaults?.headers) {
                                        delete client.defaults.headers.common['Authorization'];
                                    }
                                } catch {
                                    // ignore — logout must always succeed locally.
                                }
                                queryClient.clear();
                                navigate('/login');
                            }}
                        />
                    </div>

                    {/* Sidebar (renders SECOND on mobile) */}
                    <div className="order-2 lg:order-1 lg:col-span-1">
                        <ProfileSidebar
                            roles={profile.roles}
                            department={profile.department}
                            position={profile.position}
                        />
                    </div>
                </div>
            </main>
            <Footer />
        </div>
    );
};

export default Settings;

// ─── Personal info card (last_name / first_name / patronymic / display / bio) ─

const personalSchema = z.object({
    last_name: z.string().max(150).optional().or(z.literal('')),
    first_name: z.string().max(150).optional().or(z.literal('')),
    patronymic: z.string().max(100).optional().or(z.literal('')),
    display_name: z.string().max(100).optional().or(z.literal('')),
    bio: z.string().max(2000).optional().or(z.literal('')),
});

type PersonalFormValues = z.infer<typeof personalSchema>;

const PersonalInfoCard: React.FC<{ profile: UserProfile }> = ({ profile }) => {
    const { t } = useTranslation();
    const queryClient = useQueryClient();

    const initial: PersonalFormValues = {
        last_name: profile.lastName || '',
        first_name: profile.firstName || '',
        patronymic: profile.patronymic || '',
        display_name: profile.display_name || '',
        bio: profile.bio || '',
    };

    const form = useForm<PersonalFormValues>({
        resolver: zodResolver(personalSchema),
        defaultValues: initial,
    });

    // Sync form values when the /profile/me query resolves after a stale
    // cache hit. Skip if the user is mid-edit so we don't blow away typing.
    useEffect(() => {
        if (form.formState.isDirty) return;
        form.reset(initial);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [
        profile.firstName,
        profile.lastName,
        profile.patronymic,
        profile.display_name,
        profile.bio,
    ]);

    const mutation = useMutation({
        mutationFn: async (values: PersonalFormValues) => {
            const formData = new FormData();
            formData.append('first_name', values.first_name || '');
            formData.append('last_name', values.last_name || '');
            formData.append('patronymic', values.patronymic || '');
            formData.append('display_name', values.display_name || '');
            formData.append('bio', values.bio || '');
            const res = await api.patch<UserProfile>('users/v1/profile/me', formData, {
                headers: { 'Content-Type': 'multipart/form-data' },
            });
            return res.data;
        },
        onSuccess: (updated) => {
            queryClient.setQueryData(['profile'], updated);
            writeCachedProfile(updated);
            // Reset dirty state so the auto-sync useEffect won't bail next time.
            form.reset({
                last_name: updated.lastName || '',
                first_name: updated.firstName || '',
                patronymic: updated.patronymic || '',
                display_name: updated.display_name || '',
                bio: updated.bio || '',
            });
            toast.success(t('settingsPage.personalSaved', 'Личные данные обновлены'));
        },
        onError: () => {
            toast.error(t('settingsPage.personalSaveError', 'Не удалось сохранить'));
        },
    });

    return (
        <Card>
            <CardHeader>
                <CardTitle className="flex items-center gap-2">
                    <UserCircle className="h-5 w-5" />
                    {t('settingsPage.personalTitle', 'Личные данные')}
                </CardTitle>
                <CardDescription>
                    {t(
                        'settingsPage.personalDescription',
                        'Имя, фамилия, отчество и краткое описание для отображения в профиле и почте.',
                    )}
                </CardDescription>
            </CardHeader>
            <CardContent>
                <Form {...form}>
                    <form
                        onSubmit={form.handleSubmit((values) => mutation.mutate(values))}
                        className="space-y-4"
                    >
                        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                            <FormField
                                control={form.control}
                                name="last_name"
                                render={({ field }) => (
                                    <FormItem>
                                        <FormLabel>{t('settingsPage.lastName', 'Фамилия')}</FormLabel>
                                        <FormControl>
                                            <Input {...field} value={field.value || ''} />
                                        </FormControl>
                                        <FormMessage />
                                    </FormItem>
                                )}
                            />
                            <FormField
                                control={form.control}
                                name="first_name"
                                render={({ field }) => (
                                    <FormItem>
                                        <FormLabel>{t('settingsPage.firstName', 'Имя')}</FormLabel>
                                        <FormControl>
                                            <Input {...field} value={field.value || ''} />
                                        </FormControl>
                                        <FormMessage />
                                    </FormItem>
                                )}
                            />
                            <FormField
                                control={form.control}
                                name="patronymic"
                                render={({ field }) => (
                                    <FormItem>
                                        <FormLabel>
                                            {t('settingsPage.patronymic', 'Отчество')}
                                        </FormLabel>
                                        <FormControl>
                                            <Input {...field} value={field.value || ''} />
                                        </FormControl>
                                        <FormMessage />
                                    </FormItem>
                                )}
                            />
                        </div>
                        <FormField
                            control={form.control}
                            name="display_name"
                            render={({ field }) => (
                                <FormItem>
                                    <FormLabel>
                                        {t('settingsPage.displayName', 'Отображаемое имя')}
                                    </FormLabel>
                                    <FormControl>
                                        <Input {...field} value={field.value || ''} />
                                    </FormControl>
                                    <FormDescription>
                                        {t(
                                            'settingsPage.displayNameHint',
                                            'Так вас видят коллеги в чате, задачах и почте.',
                                        )}
                                    </FormDescription>
                                    <FormMessage />
                                </FormItem>
                            )}
                        />
                        <FormField
                            control={form.control}
                            name="bio"
                            render={({ field }) => (
                                <FormItem>
                                    <FormLabel>{t('settingsPage.bio', 'О себе')}</FormLabel>
                                    <FormControl>
                                        <Textarea
                                            rows={4}
                                            {...field}
                                            value={field.value || ''}
                                        />
                                    </FormControl>
                                    <FormMessage />
                                </FormItem>
                            )}
                        />
                        <div className="flex justify-end">
                            <Button type="submit" disabled={mutation.isPending}>
                                {mutation.isPending
                                    ? t('common.saving', 'Сохранение...')
                                    : t('settingsPage.save', 'Сохранить')}
                            </Button>
                        </div>
                    </form>
                </Form>
            </CardContent>
        </Card>
    );
};

// ─── Contact info card (phone + secondary email) ─────────────────────────────

const contactSchema = z.object({
    // Маска (PhoneInput) не даёт набрать лишнего, но недобранный номер
    // сохранить всё же можно — это ловим здесь. Схема объявлена вне
    // компонента, поэтому хук t() недоступен; сообщение берём из общего
    // инстанса i18n и обязательно лениво — колбэк zod зовёт его на каждой
    // валидации, а строковый литерал зафиксировал бы язык на момент импорта.
    phone: z
        .string()
        .max(30)
        .refine(isKzPhoneValid, () => ({
            message: i18n.t('settingsPage.phoneIncomplete'),
        }))
        .optional()
        .or(z.literal('')),
});

type ContactFormValues = z.infer<typeof contactSchema>;

const ContactInfoCard: React.FC<{ profile: UserProfile }> = ({ profile }) => {
    const { t } = useTranslation();
    const queryClient = useQueryClient();

    const form = useForm<ContactFormValues>({
        resolver: zodResolver(contactSchema),
        defaultValues: {
            phone: profile.phone || '',
        },
    });

    // react-hook-form snapshots `defaultValues` on first render. When the
    // /profile/me request resolves *after* a stale cache placeholder, the
    // inputs would otherwise stay empty — re-sync via reset().
    useEffect(() => {
        if (form.formState.isDirty) return; // don't clobber unsaved edits
        form.reset({ phone: profile.phone || '' });
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [profile.phone]);

    const mutation = useMutation({
        mutationFn: async (values: ContactFormValues) => {
            const formData = new FormData();
            formData.append('phone', values.phone || '');
            const res = await api.patch<UserProfile>('users/v1/profile/me', formData, {
                headers: { 'Content-Type': 'multipart/form-data' },
            });
            return res.data;
        },
        onSuccess: (updated) => {
            queryClient.setQueryData(['profile'], updated);
            writeCachedProfile(updated);
            form.reset({ phone: updated.phone || '' });
            toast.success(t('settingsPage.contactSaved', 'Контактные данные обновлены'));
        },
        onError: () => {
            toast.error(t('settingsPage.contactSaveError', 'Не удалось сохранить'));
        },
    });

    return (
        <Card>
            <CardHeader>
                <CardTitle className="flex items-center gap-2">
                    <Phone className="h-5 w-5" />
                    {t('settingsPage.contactTitle', 'Контактные данные')}
                </CardTitle>
                <CardDescription>
                    {t(
                        'settingsPage.contactDescription',
                        'Номер телефона и дополнительная почта для связи и восстановления доступа.',
                    )}
                </CardDescription>
            </CardHeader>
            <CardContent>
                <Form {...form}>
                    <form
                        onSubmit={form.handleSubmit((values) => mutation.mutate(values))}
                        className="space-y-4"
                    >
                        <FormField
                            control={form.control}
                            name="phone"
                            render={({ field }) => (
                                <FormItem>
                                    <FormLabel>{t('settingsPage.phone', 'Номер телефона')}</FormLabel>
                                    <FormControl>
                                        <PhoneInput {...field} value={field.value || ''} />
                                    </FormControl>
                                    <FormMessage />
                                </FormItem>
                            )}
                        />
                        <div className="flex justify-end">
                            <Button type="submit" disabled={mutation.isPending}>
                                {mutation.isPending
                                    ? t('common.saving', 'Сохранение...')
                                    : t('settingsPage.save', 'Сохранить')}
                            </Button>
                        </div>
                    </form>
                </Form>

                {/* Вне <form> намеренно: у почты свои действия («Подключить»,
                    «Сохранить подпись») со своей проверкой на сервере, и
                    отправлять их общей кнопкой «Сохранить» значило бы обещать
                    одно сохранение там, где их два и они независимы. */}
                <Separator className="my-6" />
                <CorporateMailSettings />
            </CardContent>
        </Card>
    );
};

// ─── Work info card (HR-managed, read-only) ──────────────────────────────────

interface HrEmployeeMe {
    id: number;
    user_id: number | null;
    first_name: string;
    last_name: string;
    middle_name?: string | null;
    email: string;
    phone?: string | null;
    hire_date?: string | null;
    termination_date?: string | null;
    status: string;
    bio?: string | null;
    department?: { id: number; name: string } | null;
    position?: { id: number; title: string } | null;
}

function fmtDate(iso?: string | null): string {
    if (!iso) return '—';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleDateString();
}

const WorkInfoCard: React.FC = () => {
    const { t } = useTranslation();

    const { data, isLoading, error } = useQuery<HrEmployeeMe>({
        queryKey: ['hr', 'employee', 'me'],
        queryFn: async () => {
            const res = await api.get<HrEmployeeMe>('hr/v1/employees/me/');
            return res.data;
        },
        retry: false, // 404 = no HR record yet, don't keep banging
    });

    return (
        <Card>
            <CardHeader>
                <CardTitle className="flex items-center gap-2">
                    <Briefcase className="h-5 w-5" />
                    {t('settingsPage.workTitle', 'Кадровые данные')}
                </CardTitle>
                <CardDescription>
                    {t(
                        'settingsPage.workDescription',
                        'Что HR/администратор указали при оформлении. Изменения возможны только через HR-раздел.',
                    )}
                </CardDescription>
            </CardHeader>
            <CardContent>
                {isLoading && (
                    <p className="text-sm text-muted-foreground">
                        {t('common.loading', 'Загрузка...')}
                    </p>
                )}
                {error && !isLoading && (
                    <p className="text-sm text-muted-foreground">
                        {t(
                            'settingsPage.workEmpty',
                            'Кадровая запись ещё не создана. Обратитесь к HR.',
                        )}
                    </p>
                )}
                {data && (
                    <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3 text-sm">
                        <div>
                            <dt className="text-muted-foreground">
                                {t('settingsPage.lastName', 'Фамилия')}
                            </dt>
                            <dd className="font-medium">{data.last_name || '—'}</dd>
                        </div>
                        <div>
                            <dt className="text-muted-foreground">
                                {t('settingsPage.firstName', 'Имя')}
                            </dt>
                            <dd className="font-medium">{data.first_name || '—'}</dd>
                        </div>
                        <div>
                            <dt className="text-muted-foreground">
                                {t('settingsPage.patronymic', 'Отчество')}
                            </dt>
                            <dd className="font-medium">{data.middle_name || '—'}</dd>
                        </div>
                        <div>
                            <dt className="text-muted-foreground flex items-center gap-1">
                                <Building2 className="h-3.5 w-3.5" />
                                {t('settingsPage.department', 'Отдел')}
                            </dt>
                            <dd className="font-medium">
                                {data.department?.name || '—'}
                            </dd>
                        </div>
                        <div>
                            <dt className="text-muted-foreground flex items-center gap-1">
                                <Briefcase className="h-3.5 w-3.5" />
                                {t('settingsPage.position', 'Должность')}
                            </dt>
                            <dd className="font-medium">
                                {data.position?.title || '—'}
                            </dd>
                        </div>
                        <div>
                            <dt className="text-muted-foreground flex items-center gap-1">
                                <CalendarDays className="h-3.5 w-3.5" />
                                {t('settingsPage.hireDate', 'Дата найма')}
                            </dt>
                            <dd className="font-medium">{fmtDate(data.hire_date)}</dd>
                        </div>
                        <div>
                            <dt className="text-muted-foreground flex items-center gap-1">
                                <Mail className="h-3.5 w-3.5" />
                                {t('settingsPage.workEmail', 'Рабочая почта')}
                            </dt>
                            <dd className="font-medium">{data.email || '—'}</dd>
                        </div>
                        <div>
                            <dt className="text-muted-foreground flex items-center gap-1">
                                <Phone className="h-3.5 w-3.5" />
                                {t('settingsPage.workPhone', 'Рабочий телефон')}
                            </dt>
                            <dd className="font-medium">{data.phone || '—'}</dd>
                        </div>
                        <div>
                            <dt className="text-muted-foreground">
                                {t('settingsPage.status', 'Статус')}
                            </dt>
                            <dd className="font-medium capitalize">{data.status}</dd>
                        </div>
                        {data.termination_date && (
                            <div>
                                <dt className="text-muted-foreground">
                                    {t('settingsPage.terminationDate', 'Дата увольнения')}
                                </dt>
                                <dd className="font-medium">
                                    {fmtDate(data.termination_date)}
                                </dd>
                            </div>
                        )}
                        {data.bio && (
                            <div className="sm:col-span-2">
                                <dt className="text-muted-foreground">
                                    {t('settingsPage.workBio', 'О сотруднике')}
                                </dt>
                                <dd className="whitespace-pre-wrap">{data.bio}</dd>
                            </div>
                        )}
                    </dl>
                )}
            </CardContent>
        </Card>
    );
};

// ─── Password change card ────────────────────────────────────────────────────

const passwordSchema = z
    .object({
        current_password: z.string().min(1, 'required'),
        new_password: z.string().min(8, 'min8'),
        confirm_password: z.string().min(8, 'min8'),
    })
    .refine((data) => data.new_password === data.confirm_password, {
        path: ['confirm_password'],
        message: 'mismatch',
    });

type PasswordFormValues = z.infer<typeof passwordSchema>;

const PasswordCard: React.FC = () => {
    const { t } = useTranslation();

    const form = useForm<PasswordFormValues>({
        resolver: zodResolver(passwordSchema),
        defaultValues: { current_password: '', new_password: '', confirm_password: '' },
    });

    const mutation = useMutation({
        mutationFn: async (values: PasswordFormValues) => {
            const res = await api.post('users/v1/profile/change-password/', {
                current_password: values.current_password,
                new_password: values.new_password,
            });
            return res.data;
        },
        onSuccess: () => {
            toast.success(t('settingsPage.passwordChanged', 'Пароль изменён'));
            form.reset();
        },
        onError: (err: any) => {
            const detail = err?.response?.data?.detail;
            toast.error(
                detail || t('settingsPage.passwordChangeError', 'Не удалось изменить пароль'),
            );
        },
    });

    return (
        <Card>
            <CardHeader>
                <CardTitle className="flex items-center gap-2">
                    <KeyRound className="h-5 w-5" />
                    {t('settingsPage.passwordTitle', 'Смена пароля')}
                </CardTitle>
                <CardDescription>
                    {t(
                        'settingsPage.passwordDescription',
                        'Минимум 8 символов. Используйте уникальный пароль, не повторяющий другие сервисы.',
                    )}
                </CardDescription>
            </CardHeader>
            <CardContent>
                <Form {...form}>
                    <form
                        onSubmit={form.handleSubmit((values) => mutation.mutate(values))}
                        className="space-y-4"
                    >
                        <FormField
                            control={form.control}
                            name="current_password"
                            render={({ field }) => (
                                <FormItem>
                                    <FormLabel>
                                        {t('settingsPage.currentPassword', 'Текущий пароль')}
                                    </FormLabel>
                                    <FormControl>
                                        <Input type="password" autoComplete="current-password" {...field} />
                                    </FormControl>
                                    <FormMessage />
                                </FormItem>
                            )}
                        />
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <FormField
                                control={form.control}
                                name="new_password"
                                render={({ field }) => (
                                    <FormItem>
                                        <FormLabel>
                                            {t('settingsPage.newPassword', 'Новый пароль')}
                                        </FormLabel>
                                        <FormControl>
                                            <Input type="password" autoComplete="new-password" {...field} />
                                        </FormControl>
                                        <FormMessage />
                                    </FormItem>
                                )}
                            />
                            <FormField
                                control={form.control}
                                name="confirm_password"
                                render={({ field }) => (
                                    <FormItem>
                                        <FormLabel>
                                            {t('settingsPage.confirmPassword', 'Подтверждение')}
                                        </FormLabel>
                                        <FormControl>
                                            <Input type="password" autoComplete="new-password" {...field} />
                                        </FormControl>
                                        <FormMessage />
                                    </FormItem>
                                )}
                            />
                        </div>
                        <div className="flex justify-end">
                            <Button type="submit" disabled={mutation.isPending}>
                                {mutation.isPending
                                    ? t('common.saving', 'Сохранение...')
                                    : t('settingsPage.changePassword', 'Изменить пароль')}
                            </Button>
                        </div>
                    </form>
                </Form>
            </CardContent>
        </Card>
    );
};

// ─── Account / logout card ───────────────────────────────────────────────────

const AccountCard: React.FC<{ email: string; onLogout: () => Promise<void> }> = ({
    email,
    onLogout,
}) => {
    const { t } = useTranslation();
    const [pending, setPending] = useState(false);

    const handleLogout = async () => {
        setPending(true);
        try {
            await onLogout();
        } finally {
            setPending(false);
        }
    };

    return (
        <Card>
            <CardHeader>
                <CardTitle className="flex items-center gap-2">
                    <ShieldCheck className="h-5 w-5" />
                    {t('settingsPage.accountTitle', 'Аккаунт')}
                </CardTitle>
                <CardDescription>
                    {t('settingsPage.accountDescription', 'Основной email и выход из системы.')}
                </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
                <div className="text-sm">
                    <span className="text-muted-foreground">
                        {t('settingsPage.primaryEmail', 'Основная почта')}:
                    </span>{' '}
                    <span className="font-medium">{email}</span>
                </div>
                <Separator />
                <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                    <p className="text-sm text-muted-foreground">
                        {t(
                            'settingsPage.logoutHint',
                            'Завершит сессию на этом устройстве и очистит локальные данные.',
                        )}
                    </p>
                    <Button
                        variant="destructive"
                        onClick={handleLogout}
                        disabled={pending}
                        className="flex items-center gap-2"
                    >
                        <LogOut className="h-4 w-4" />
                        {pending
                            ? t('settingsPage.loggingOut', 'Выход...')
                            : t('profile.logout', 'Выйти')}
                    </Button>
                </div>
            </CardContent>
        </Card>
    );
};
