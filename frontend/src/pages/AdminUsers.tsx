import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { ArrowLeft, ExternalLink, Pencil, UserPlus } from 'lucide-react';
import { toast } from 'sonner';

import api from '../api/client';
import { Header } from '../components/Header';
import { Footer } from '../components/Footer';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { UserEditDialog, type AdminUser } from '@/components/admin/UserEditDialog';


interface AdminUserUpdate {
    is_staff?: boolean;
    is_superuser?: boolean;
    status?: AdminUser['status'];
    must_change_password?: boolean;
}


const STATUS_OPTIONS: AdminUser['status'][] = ['pending', 'active', 'suspended', 'rejected'];


const AdminUsers = () => {
    const { t } = useTranslation();
    const queryClient = useQueryClient();
    const [dialogOpen, setDialogOpen] = useState(false);
    const [dialogMode, setDialogMode] = useState<'create' | 'edit'>('create');
    const [editingUser, setEditingUser] = useState<AdminUser | null>(null);

    const { data: users, isLoading, error } = useQuery({
        queryKey: ['admin-users'],
        queryFn: async () => {
            const res = await api.get<AdminUser[]>('users/v1/admin/users/');
            return res.data;
        }
    });

    const updateMutation = useMutation({
        mutationFn: ({ id, patch }: { id: number; patch: AdminUserUpdate }) =>
            api.patch<AdminUser>(`users/v1/admin/users/${id}/`, patch).then(r => r.data),
        onSuccess: (updated) => {
            queryClient.setQueryData<AdminUser[]>(['admin-users'], (prev) =>
                prev?.map(u => u.id === updated.id ? { ...u, ...updated } : u),
            );
            toast.success(t('admin.users.saved', 'Изменения сохранены'));
        },
        onError: (err: any) => {
            toast.error(err?.response?.data?.detail ?? t('admin.users.saveError', 'Не удалось обновить пользователя'));
        },
    });

    const openCreate = () => {
        setEditingUser(null);
        setDialogMode('create');
        setDialogOpen(true);
    };

    const openEdit = (user: AdminUser) => {
        setEditingUser(user);
        setDialogMode('edit');
        setDialogOpen(true);
    };

    if (isLoading) return <div className="min-h-screen flex items-center justify-center">Loading...</div>;
    if (error) return (
        <div className="min-h-screen bg-background flex flex-col">
            <Header />
            <main className="flex-1 container mx-auto px-4 py-8 flex items-center justify-center">
                <div className="text-center">
                    <h1 className="text-2xl font-bold text-red-500 mb-2">Access Denied</h1>
                    <p>You do not have permission to view this page.</p>
                </div>
            </main>
            <Footer />
        </div>
    );

    const formatLogin = (iso: string | null | undefined) => iso ? new Date(iso).toLocaleString() : '—';

    return (
        <div className="min-h-screen bg-background flex flex-col">
            <Header />
            <main className="flex-1 container mx-auto px-4 py-8">
                <div className="mb-6 flex flex-col gap-4">
                    <Link
                        to="/myprofile"
                        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors w-fit"
                    >
                        <ArrowLeft className="h-4 w-4" />
                        {t('hr.backToMain', 'Назад в профиль')}
                    </Link>
                    <div className="flex flex-wrap items-center justify-between gap-3">
                        <div>
                            <h1 className="text-3xl font-bold">{t('admin.users.title', 'Управление пользователями')}</h1>
                            <p className="text-sm text-muted-foreground mt-1">
                                {t('admin.users.subtitle', 'Создавайте новых пользователей и редактируйте существующих. Для прямого доступа к таблицам БД — ')}
                                <a href="/sqladmin/" className="text-primary hover:underline inline-flex items-center gap-1">sqladmin <ExternalLink className="h-3 w-3"/></a>.
                            </p>
                        </div>
                        <div className="flex items-center gap-3">
                            <div className="flex items-center gap-2 text-sm">
                                <Link to="/admin/registrations" className="text-primary hover:underline">→ Заявки</Link>
                                <span className="text-muted-foreground">|</span>
                                <Link to="/admin/chats" className="text-primary hover:underline">→ Чаты</Link>
                            </div>
                            <Button onClick={openCreate} className="flex items-center gap-2">
                                <UserPlus className="h-4 w-4" />
                                {t('admin.users.createBtn', 'Создать пользователя')}
                            </Button>
                        </div>
                    </div>
                </div>
                <div className="bg-card rounded-lg border overflow-x-auto">
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead>{t('admin.users.username', 'Username')}</TableHead>
                                <TableHead>{t('admin.users.email', 'Email')}</TableHead>
                                <TableHead>{t('admin.users.joined', 'Joined')}</TableHead>
                                <TableHead>Last login</TableHead>
                                <TableHead>Status</TableHead>
                                <TableHead>is_staff</TableHead>
                                <TableHead>is_superuser</TableHead>
                                <TableHead>Role</TableHead>
                                <TableHead className="text-right">{t('admin.users.actions', 'Действия')}</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {users?.map((user) => {
                                const role =
                                    user.is_superuser ? 'admin'
                                        : user.is_staff ? 'staff'
                                            : 'user';
                                const roleVariant =
                                    role === 'admin' ? 'destructive'
                                        : role === 'staff' ? 'default'
                                            : 'outline';
                                return (
                                    <TableRow key={user.id}>
                                        <TableCell className="font-medium">
                                            {user.username}
                                            {user.display_name && user.display_name !== user.username ? (
                                                <span className="block text-xs text-muted-foreground">{user.display_name}</span>
                                            ) : null}
                                        </TableCell>
                                        <TableCell>{user.email}</TableCell>
                                        <TableCell>{user.date_joined ? new Date(user.date_joined).toLocaleDateString() : '—'}</TableCell>
                                        <TableCell className="text-muted-foreground text-xs">{formatLogin(user.last_login)}</TableCell>
                                        <TableCell>
                                            <Select
                                                value={user.status}
                                                onValueChange={(value) =>
                                                    updateMutation.mutate({ id: user.id, patch: { status: value as AdminUser['status'] } })
                                                }
                                                disabled={updateMutation.isPending}
                                            >
                                                <SelectTrigger className="w-[130px] h-8">
                                                    <SelectValue />
                                                </SelectTrigger>
                                                <SelectContent>
                                                    {STATUS_OPTIONS.map((s) => (
                                                        <SelectItem key={s} value={s}>{s}</SelectItem>
                                                    ))}
                                                </SelectContent>
                                            </Select>
                                        </TableCell>
                                        <TableCell>
                                            <Switch
                                                checked={user.is_staff}
                                                onCheckedChange={(value) =>
                                                    updateMutation.mutate({ id: user.id, patch: { is_staff: value } })
                                                }
                                                disabled={updateMutation.isPending}
                                            />
                                        </TableCell>
                                        <TableCell>
                                            <Switch
                                                checked={user.is_superuser}
                                                onCheckedChange={(value) =>
                                                    updateMutation.mutate({ id: user.id, patch: { is_superuser: value } })
                                                }
                                                disabled={updateMutation.isPending}
                                            />
                                        </TableCell>
                                        <TableCell>
                                            <Badge variant={roleVariant}>{role}</Badge>
                                        </TableCell>
                                        <TableCell className="text-right">
                                            <Button
                                                variant="ghost"
                                                size="sm"
                                                onClick={() => openEdit(user)}
                                                className="flex items-center gap-1.5 ml-auto"
                                            >
                                                <Pencil className="h-3.5 w-3.5" />
                                                {t('admin.users.edit', 'Изменить')}
                                            </Button>
                                        </TableCell>
                                    </TableRow>
                                );
                            })}
                        </TableBody>
                    </Table>
                </div>
            </main>
            <Footer />

            <UserEditDialog
                open={dialogOpen}
                onOpenChange={setDialogOpen}
                mode={dialogMode}
                user={editingUser}
            />
        </div>
    );
};

export default AdminUsers;
