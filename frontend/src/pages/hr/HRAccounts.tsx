import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import {
  fetchPlatformAccounts,
  resetPlatformAccountPassword,
  type PlatformAccount,
} from '@/api/accounts';
import HRLayout from '@/components/hr/HRLayout';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { RefreshCw, Copy, Check } from 'lucide-react';

const HRAccounts = () => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState('');
  const [tempPassword, setTempPassword] = useState<{ id: number; pw: string } | null>(null);
  const [copiedId, setCopiedId] = useState<number | null>(null);

  const { data: accounts, isLoading, error } = useQuery({
    queryKey: ['hr-accounts'],
    queryFn: fetchPlatformAccounts,
  });

  const resetMutation = useMutation({
    mutationFn: (id: number) => resetPlatformAccountPassword(id),
    onSuccess: (pw, id) => {
      setTempPassword({ id, pw });
      queryClient.invalidateQueries({ queryKey: ['hr-accounts'] });
    },
    onError: (err: any) =>
      toast.error(err?.response?.data?.detail ?? t('hr.pages.accounts.error')),
  });

  const filtered = (accounts || []).filter((a) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (
      a.username?.toLowerCase().includes(q) ||
      a.email?.toLowerCase().includes(q) ||
      `${a.first_name ?? ''} ${a.last_name ?? ''}`.toLowerCase().includes(q)
    );
  });

  const roleOf = (a: PlatformAccount) =>
    a.is_superuser ? 'admin' : a.is_staff ? 'staff' : 'user';

  if (isLoading)
    return (
      <HRLayout title={t('hr.pages.accounts.title')} subtitle={t('hr.pages.accounts.subtitle')}>
        <div className="p-8">{t('hr.common.loading')}</div>
      </HRLayout>
    );
  if (error)
    return (
      <HRLayout title={t('hr.pages.accounts.title')} subtitle={t('hr.pages.accounts.subtitle')}>
        <div className="p-8 text-red-500">{t('hr.pages.accounts.error')}</div>
      </HRLayout>
    );

  return (
    <HRLayout title={t('hr.pages.accounts.title')} subtitle={t('hr.pages.accounts.subtitle')}>
      <div className="mb-4">
        <Input
          placeholder={t('hr.pages.accounts.searchPlaceholder')}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="max-w-sm"
        />
      </div>

      <div className="border rounded-lg overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t('hr.pages.accounts.fields.username')}</TableHead>
              <TableHead>{t('hr.pages.accounts.fields.email')}</TableHead>
              <TableHead>{t('hr.pages.accounts.fields.status')}</TableHead>
              <TableHead>{t('admin.users.role', 'Роль')}</TableHead>
              <TableHead>{t('hr.common.actions')}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.map((a) => (
              <TableRow key={a.id}>
                <TableCell className="font-medium">
                  <code className="bg-muted px-2 py-1 rounded text-sm">{a.username}</code>
                  {tempPassword?.id === a.id && (
                    <div className="mt-1 flex items-center gap-2 text-xs">
                      <code className="bg-amber-100 px-2 py-1 rounded">{tempPassword.pw}</code>
                      <Button
                        size="icon"
                        variant="ghost"
                        className="h-6 w-6"
                        onClick={async () => {
                          await navigator.clipboard.writeText(tempPassword.pw);
                          setCopiedId(a.id);
                          setTimeout(() => setCopiedId(null), 2000);
                        }}
                      >
                        {copiedId === a.id ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
                      </Button>
                    </div>
                  )}
                </TableCell>
                <TableCell>{a.email}</TableCell>
                <TableCell>
                  <Badge variant={a.status === 'active' ? 'default' : 'secondary'}>{a.status}</Badge>
                </TableCell>
                <TableCell>
                  <Badge variant="outline">{roleOf(a)}</Badge>
                </TableCell>
                <TableCell>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => resetMutation.mutate(a.id)}
                    disabled={resetMutation.isPending}
                  >
                    <RefreshCw className="h-3.5 w-3.5 mr-1" />
                    {t('hr.pages.accounts.resetPassword')}
                  </Button>
                </TableCell>
              </TableRow>
            ))}
            {filtered.length === 0 && (
              <TableRow>
                <TableCell colSpan={5} className="text-center py-8 text-muted-foreground">
                  {t('hr.pages.accounts.empty')}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </HRLayout>
  );
};

export default HRAccounts;
