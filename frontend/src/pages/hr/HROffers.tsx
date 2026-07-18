import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import api from '@/api/client';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { useHRLevel } from '@/hooks/useHRLevel';

interface Application {
  id: number;
  vacancy_title: string;
  first_name: string;
  last_name: string;
  email: string;
  status: 'new' | 'reviewed' | 'interview' | 'offered' | 'rejected' | 'hired';
  created_at: string;
}

const HROffers = () => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { isSenior } = useHRLevel();

  const { data: applications = [], isLoading, error } = useQuery({
    queryKey: ['hr-offers'],
    queryFn: async () => {
      const res = await api.get<Application[]>('hr/v1/applications/');
      return res.data;
    },
  });

  const updateStatusMutation = useMutation({
    mutationFn: async ({ id, status }: { id: number; status: 'hired' | 'rejected' | 'offered' }) => {
      const res = await api.patch(`hr/v1/applications/${id}/`, { status });
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hr-offers'] });
      queryClient.invalidateQueries({ queryKey: ['hr-applications'] });
    },
  });

  const offerApplications = applications.filter((app) =>
    app.status === 'offered' || app.status === 'hired' || app.status === 'rejected',
  );

  const statusLabel = (status: Application['status']) => {
    if (status === 'offered') return t('hr.pages.offers.status.offered');
    if (status === 'hired') return t('hr.pages.offers.status.hired');
    if (status === 'rejected') return t('hr.pages.offers.status.rejected');
    return status;
  };

  const statusVariant = (status: Application['status']) => {
    if (status === 'hired') return 'default' as const;
    if (status === 'rejected') return 'destructive' as const;
    return 'secondary' as const;
  };

  if (isLoading) {
    return (
      <div className="rounded-2xl border bg-card/70 p-8 text-center">{t('hr.common.loading')}</div>
    );
  }

  if (error) {
    return (
      <div className="rounded-2xl border bg-card/70 p-8 text-center text-red-500">
        {t('hr.pages.offers.error')}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="text-sm text-muted-foreground">{t('hr.common.total')}: {offerApplications.length}</div>

      <div className="bg-card rounded-2xl border overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t('hr.pages.offers.table.candidate')}</TableHead>
              <TableHead>{t('hr.pages.offers.table.email')}</TableHead>
              <TableHead>{t('hr.pages.offers.table.vacancy')}</TableHead>
              <TableHead>{t('hr.pages.offers.table.status')}</TableHead>
              <TableHead>{t('hr.pages.offers.table.date')}</TableHead>
              <TableHead className="text-right">{t('hr.pages.offers.table.actions')}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {offerApplications.length === 0 && (
              <TableRow>
                <TableCell colSpan={6} className="text-center text-muted-foreground py-8">
                  {t('hr.pages.offers.empty')}
                </TableCell>
              </TableRow>
            )}

            {offerApplications.map((app) => (
              <TableRow key={app.id}>
                <TableCell className="font-medium">{app.first_name} {app.last_name}</TableCell>
                <TableCell>{app.email}</TableCell>
                <TableCell>{app.vacancy_title}</TableCell>
                <TableCell>
                  <Badge variant={statusVariant(app.status)}>{statusLabel(app.status)}</Badge>
                </TableCell>
                <TableCell>{new Date(app.created_at).toLocaleDateString()}</TableCell>
                <TableCell className="text-right">
                  <div className="flex justify-end gap-2">
                    {app.status !== 'offered' && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => updateStatusMutation.mutate({ id: app.id, status: 'offered' })}
                        disabled={!isSenior || updateStatusMutation.isPending}
                        title={!isSenior ? t('hr.pages.offers.seniorOnly') : ''}
                      >
                        {t('hr.pages.offers.actions.return')}
                      </Button>
                    )}
                    <Button
                      size="sm"
                      onClick={() => updateStatusMutation.mutate({ id: app.id, status: 'hired' })}
                      disabled={app.status !== 'offered' || updateStatusMutation.isPending || !isSenior}
                      title={!isSenior ? t('hr.pages.offers.seniorOnly') : ''}
                    >
                      {t('hr.pages.offers.actions.accept')}
                    </Button>
                    <Button
                      size="sm"
                      variant="destructive"
                      onClick={() => updateStatusMutation.mutate({ id: app.id, status: 'rejected' })}
                      disabled={app.status !== 'offered' || updateStatusMutation.isPending || !isSenior}
                      title={!isSenior ? t('hr.pages.offers.seniorOnly') : ''}
                    >
                      {t('hr.pages.offers.actions.reject')}
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
};

export default HROffers;