import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import api from '@/api/client';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { FileWarning, Lock } from 'lucide-react';
import { toast } from '@/hooks/use-toast';

export const ForcePasswordChange = () => {
    const { t } = useTranslation();
    const queryClient = useQueryClient();
    const [password, setPassword] = useState('');
    const [confirm, setConfirm] = useState('');

    const mutation = useMutation({
        mutationFn: async (new_password: string) => {
            const res = await api.post('users/v1/profile/change-password/', { new_password });
            return res.data;
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['profile'] });
            toast({
                title: t('auth.passwordChanged'),
                description: t('auth.passwordChangedSuccess'),
                variant: 'default',
            });
        },
        onError: (err: any) => {
            toast({
                title: t('auth.passwordChangeError'),
                description: err?.response?.data?.detail || t('common.error'),
                variant: 'destructive',
            });
        }
    });

    const handleSubmit = (e: React.FormEvent) => {
        e.preventDefault();
        if (password !== confirm) {
            toast({
                title: t('auth.passwordsDoNotMatch'),
                variant: 'destructive',
            });
            return;
        }
        if (password.length < 8) {
            toast({
                title: t('auth.passwordTooShort'),
                variant: 'destructive',
            });
            return;
        }
        mutation.mutate(password);
    };

    return (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-background/80 backdrop-blur-sm p-4">
            <Card className="max-w-md w-full shadow-lg border-2 border-primary/20">
                <CardHeader className="text-center space-y-2">
                    <div className="mx-auto bg-primary/10 p-3 rounded-full w-fit mb-2">
                        <Lock className="w-8 h-8 text-primary" />
                    </div>
                    <CardTitle className="text-2xl">{t('auth.forcePasswordChangeTitle')}</CardTitle>
                    <CardDescription className="text-base text-muted-foreground">
                        {t('auth.forcePasswordChangeDesc')}
                    </CardDescription>
                </CardHeader>
                <CardContent>
                    <form onSubmit={handleSubmit} className="space-y-4">
                        <div className="space-y-2">
                            <label className="text-sm font-medium">{t('auth.newPassword')}</label>
                            <Input
                                type="password"
                                value={password}
                                onChange={(e) => setPassword(e.target.value)}
                                required
                                minLength={8}
                                placeholder="••••••••"
                            />
                        </div>
                        <div className="space-y-2">
                            <label className="text-sm font-medium">{t('auth.confirmPassword')}</label>
                            <Input
                                type="password"
                                value={confirm}
                                onChange={(e) => setConfirm(e.target.value)}
                                required
                                minLength={8}
                                placeholder="••••••••"
                            />
                        </div>

                        <div className="bg-muted/50 p-3 rounded-md flex items-start gap-2 mt-4 text-sm text-muted-foreground">
                            <FileWarning className="w-4 h-4 mt-0.5 text-primary shrink-0" />
                            <p>{t('auth.forcePasswordWarning')}</p>
                        </div>

                        <Button
                            type="submit"
                            className="w-full mt-6"
                            size="lg"
                            disabled={mutation.isPending || !password || !confirm}
                        >
                            {mutation.isPending ? t('common.saving') : t('auth.saveNewPassword')}
                        </Button>
                    </form>
                </CardContent>
            </Card>
        </div>
    );
};
