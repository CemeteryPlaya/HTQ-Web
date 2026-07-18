import React from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import api from '@/api/client';
import { Header } from '@/components/Header';
import { Footer } from '@/components/Footer';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { toast } from 'sonner';
import { CheckCircle, XCircle, ArrowLeft } from 'lucide-react';
import { Link } from 'react-router-dom';

interface PendingUser {
  id: number;
  full_name?: string;
  username: string;
  email: string;
  date_joined: string;
}

const AdminRegistrations = () => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const { data: users, isLoading } = useQuery({
    queryKey: ['pending-registrations'],
    queryFn: async () => {
      const res = await api.get('users/v1/pending-registrations/');
      return res.data as PendingUser[];
    },
  });

  const approveMutation = useMutation({
    mutationFn: (id: number) => api.post(`users/v1/pending-registrations/${id}/approve/`),
    onSuccess: (_, id) => {
      queryClient.invalidateQueries({ queryKey: ['pending-registrations'] });
      toast.success(t('admin.registrations.approved'));
    },
  });

  const rejectMutation = useMutation({
    mutationFn: (id: number) => api.post(`users/v1/pending-registrations/${id}/reject/`),
    onSuccess: (_, id) => {
      queryClient.invalidateQueries({ queryKey: ['pending-registrations'] });
      toast.success(t('admin.registrations.rejected'));
    },
  });

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

          <div className="flex items-center justify-between">
            <h1 className="text-3xl font-bold">{t('admin.registrations.title')}</h1>
            {users && users.length > 0 && (
              <Badge variant="secondary">{users.length} {t('admin.registrations.pending')}</Badge>
            )}
          </div>
        </div>

        {isLoading ? (
          <p className="text-muted-foreground">{t('common.loading', 'Loading...')}</p>
        ) : !users || users.length === 0 ? (
          <div className="text-center py-12 text-muted-foreground">
            <CheckCircle className="mx-auto mb-3 h-12 w-12 opacity-30" />
            <p>{t('admin.registrations.noPending')}</p>
          </div>
        ) : (
          <div className="border rounded-lg">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('admin.registrations.fullName')}</TableHead>
                  <TableHead>{t('admin.registrations.emailCol')}</TableHead>
                  <TableHead>{t('admin.registrations.registered')}</TableHead>
                  <TableHead className="text-right">{t('admin.registrations.actions')}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {users.map(user => (
                  <TableRow key={user.id}>
                    <TableCell className="font-medium">
                      {user.full_name || user.username}
                    </TableCell>
                    <TableCell>{user.email}</TableCell>
                    <TableCell>{new Date(user.date_joined).toLocaleDateString()}</TableCell>
                    <TableCell className="text-right space-x-2">
                      <Button
                        size="sm"
                        variant="default"
                        onClick={() => approveMutation.mutate(user.id)}
                        disabled={approveMutation.isPending || rejectMutation.isPending}
                      >
                        <CheckCircle className="h-4 w-4 mr-1" />
                        {t('admin.registrations.approve')}
                      </Button>
                      <Button
                        size="sm"
                        variant="destructive"
                        onClick={() => rejectMutation.mutate(user.id)}
                        disabled={approveMutation.isPending || rejectMutation.isPending}
                      >
                        <XCircle className="h-4 w-4 mr-1" />
                        {t('admin.registrations.reject')}
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </main>
      <Footer />
    </div>
  );
};

export default AdminRegistrations;
