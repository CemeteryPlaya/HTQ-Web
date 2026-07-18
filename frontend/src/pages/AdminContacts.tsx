import React from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import api from '@/api/client';
import { Header } from '@/components/Header';
import { Footer } from '@/components/Footer';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import { Link } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { apiPath } from '@/api/endpoints';

interface ContactRequest {
  id: number;
  first_name: string;
  last_name: string;
  email: string;
  message: string;
  handled: boolean;
  created_at: string;
}

const AdminContacts = () => {
  const queryClient = useQueryClient();
  const { t } = useTranslation();

  const { data: contacts, isLoading, error } = useQuery({
    queryKey: ['admin-contacts'],
    queryFn: async () => {
      const res = await api.get<ContactRequest[]>(apiPath('cms', 'contact-requests/'));
      return res.data;
    },
    retry: false,
    refetchInterval: 10000, // refresh every 10s
  });

  // Also fetch current profile to inspect roles / staff flag
  // also fetch current profile to inspect roles / staff flag
  const { data: profile, isLoading: profileLoading, error: profileError } = useQuery({
    queryKey: ['profile'],
    queryFn: async () => {
      const res = await api.get(apiPath('users', 'profile/me'));
      return res.data;
    },
    retry: false,
  });

  const toggleHandled = useMutation({
    mutationFn: async ({ id, handled }: { id: number; handled: boolean }) => {
      const res = await api.patch(apiPath('cms', `contact-requests/${id}/`), { handled });
      return res.data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['admin-contacts'] }),
  });

  const deleteRequest = useMutation({
    mutationFn: async (id: number) => {
      await api.delete(apiPath('cms', `contact-requests/${id}/`));
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['admin-contacts'] }),
  });

  if (isLoading || profileLoading) return <div className="min-h-screen flex items-center justify-center">{t('common.loading', 'Loading...')}</div>;

  if (error || profileError) {
    const activeError = error || profileError;
    const err = activeError as any;
    const status = err?.response?.status ?? err?.status;
    const detail = err?.response?.data || err?.message;
    return (
      <div className="min-h-screen bg-background flex flex-col">
        <Header />
        <main className="flex-1 container mx-auto px-4 py-8">
          <div className="text-center">
            <h1 className="text-2xl font-bold text-red-500 mb-2">
              {status === 500 ? t('admin.contacts.internalErrorTitle', 'Internal Server Error') : t('admin.contacts.accessDeniedTitle', 'Access Denied')}
            </h1>
            <p>{status === 500 ? t('admin.contacts.internalError', 'Something went wrong on the server.') : t('admin.contacts.accessDenied', 'You do not have permission to view this page.')}</p>
            <p className="mt-4 text-sm text-muted-foreground">{t('admin.contacts.serverResponse', 'Server response:')} {status} — {JSON.stringify(detail)}</p>
            {profileError && (
              <p className="mt-2 text-sm text-red-400">{t('admin.contacts.profileFetchFailed', 'Failed to fetch profile:')} {(profileError as any)?.response?.status}</p>
            )}
          </div>
        </main>
        <Footer />
      </div>
    );
  }



  if (!isLoading && !contacts) {
    return (
      <div className="min-h-screen bg-background flex flex-col">
        <Header />
        <main className="flex-1 container mx-auto px-4 py-8">
          <div className="text-center p-12 bg-card rounded-lg border">
            <h1 className="text-2xl font-bold mb-4">{t('admin.contacts.noDataTitle', 'No data received')}</h1>
            <p className="text-muted-foreground">{t('admin.contacts.noDataDesc', 'The server did not return any contact requests.')}</p>
          </div>
        </main>
        <Footer />
      </div>
    );
  }

  if (contacts && contacts.length === 0) {
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
            <h1 className="text-3xl font-bold">{t('admin.contacts.title', 'Contact Requests')}</h1>
          </div>
          <div className="bg-card rounded-lg border p-6">
            <p className="text-muted-foreground">{t('admin.contacts.noRequests', 'No contact requests found.')}</p>
          </div>
        </main>
        <Footer />
      </div>
    );
  }

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
          <h1 className="text-3xl font-bold">{t('admin.contacts.title', 'Contact Requests')}</h1>
        </div>
        <div className="bg-card rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t('admin.contacts.col.from', 'From')}</TableHead>
                <TableHead>{t('admin.contacts.col.email', 'Email')}</TableHead>
                <TableHead>{t('admin.contacts.col.message', 'Message')}</TableHead>
                <TableHead>{t('admin.contacts.col.received', 'Received')}</TableHead>
                <TableHead>{t('admin.contacts.col.handled', 'Handled')}</TableHead>
                <TableHead>{t('admin.contacts.col.actions', 'Actions')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {contacts?.map((c) => (
                <TableRow key={c.id}>
                  <TableCell className="font-medium">{c.first_name} {c.last_name}</TableCell>
                  <TableCell>{c.email}</TableCell>
                  <TableCell className="max-w-xl">
                    <div className="text-sm text-foreground whitespace-pre-wrap break-words">
                      {c.message}
                    </div>
                  </TableCell>
                  <TableCell>{new Date(c.created_at).toLocaleString()}</TableCell>
                  <TableCell>{c.handled ? t('admin.contacts.yes', 'Yes') : t('admin.contacts.no', 'No')}</TableCell>
                  <TableCell>
                    <div className="flex gap-2">
                      <Button size="sm" variant={c.handled ? 'outline' : 'default'} onClick={() => toggleHandled.mutate({ id: c.id, handled: !c.handled })}>
                        {c.handled ? t('admin.contacts.markUnhandled', 'Mark Unhandled') : t('admin.contacts.markHandled', 'Mark Handled')}
                      </Button>
                      <Button size="sm" variant="destructive" onClick={() => { if (confirm(t('admin.contacts.deleteConfirm', 'Delete this request?'))) deleteRequest.mutate(c.id); }}>
                        {t('admin.contacts.delete', 'Delete')}
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </main>
      <Footer />
    </div>
  );
};

export default AdminContacts;
