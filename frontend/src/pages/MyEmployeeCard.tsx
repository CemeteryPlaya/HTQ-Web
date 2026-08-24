/**
 * MyEmployeeCard — личная карточка сотрудника (/employee/me).
 *
 * Доступна любому авторизованному пользователю (без HR-роли).
 * Показывает те же данные, что и блок «Моя HR-карточка» на /myprofile,
 * но на отдельной полноценной странице с Header/Footer.
 */
import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, Share2 } from 'lucide-react';

import { fetchMyEmployeeCard, type EmployeeCard } from '@/api/hr';
import { Header } from '@/components/Header';
import { Footer } from '@/components/Footer';
import { EmployeeCardView } from '@/components/hr/EmployeeCardView';
import { ShareEmployeeDialog } from '@/components/hr/ShareEmployeeDialog';
import { Button } from '@/components/ui/button';
import { useTranslation } from 'react-i18next';

const MyEmployeeCard = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [shareOpen, setShareOpen] = useState(false);

  const { data, isLoading, error } = useQuery<EmployeeCard>({
    queryKey: ['my-hr-card'],
    queryFn: fetchMyEmployeeCard,
  });

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <Header />
      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-8 sm:px-6 lg:px-8">
        {isLoading ? (
          <div className="rounded-2xl border bg-card/70 p-8 text-center">
            {t('profile.loading')}
          </div>
        ) : error || !data ? (
          <div className="rounded-2xl border bg-card/70 p-8 text-center text-muted-foreground">
            {t('profile.employeeCardMissing')}{' '}
            <Link className="underline" to="/myprofile">
              {t('common.backToProfile')}
            </Link>
          </div>
        ) : (
          <div className="space-y-6">
            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => navigate('/myprofile')}
                className="gap-1.5"
              >
                <ArrowLeft className="h-4 w-4" />
                {t('common.back')}
              </Button>

              <h1 className="ml-2 text-2xl font-bold">{data.full_name}</h1>

              <div className="ml-auto">
                <Button
                  size="sm"
                  onClick={() => setShareOpen(true)}
                  className="gap-1.5"
                >
                  <Share2 className="h-4 w-4" />
                  {t('common.share')}
                </Button>
              </div>
            </div>

            <div className="rounded-3xl border bg-card p-6 shadow-sm">
              <EmployeeCardView card={data} mode="auth" hideHeader />
            </div>
          </div>
        )}
      </main>
      <Footer />

      {data && (
        <ShareEmployeeDialog
          open={shareOpen}
          employee={data}
          onClose={() => setShareOpen(false)}
        />
      )}
    </div>
  );
};

export default MyEmployeeCard;
