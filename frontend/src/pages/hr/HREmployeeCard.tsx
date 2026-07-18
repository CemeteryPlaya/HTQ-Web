/**
 * HREmployeeCard — полная карточка сотрудника (/hr/employees/:id).
 *
 * Открывается из таблицы /hr/employees или из любого места, где есть
 * employee.id. Содержит контакты, должность, отдел, PMO, руководителя и
 * подчинённых. Кнопка «Поделиться» открывает ShareEmployeeDialog для
 * создания одноразовой/временной публичной ссылки на этого сотрудника.
 *
 * Тот же layout переиспользуется в EmployeeCardView (без кнопок share/edit)
 * для публичной /public/employee/:token и блока «Моя HR-карточка» на
 * /myprofile.
 */
import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, Pencil, Share2 } from 'lucide-react';

import { fetchEmployeeCard, fetchCardT2 } from '@/api/hr';
import HRLayout from '@/components/hr/HRLayout';
import { EmployeeCardView } from '@/components/hr/EmployeeCardView';
import { ShareEmployeeDialog } from '@/components/hr/ShareEmployeeDialog';
import { Button } from '@/components/ui/button';
import { useHRLevel } from '@/hooks/useHRLevel';

const HREmployeeCard = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const employeeId = Number(id);
  const { hasHrAccess, canWriteBasic, hasPerm, isLoading: levelLoading } = useHRLevel();
  const [shareOpen, setShareOpen] = useState(false);

  const { data, isLoading, error } = useQuery({
    queryKey: ['hr-employee-card', employeeId],
    queryFn: () => fetchEmployeeCard(employeeId),
    enabled: Number.isFinite(employeeId) && hasHrAccess,
  });

  const { data: cardT2 } = useQuery({
    queryKey: ['hr-card-t2', employeeId],
    queryFn: () => fetchCardT2(Number(employeeId)),
    enabled: !!employeeId && (hasPerm('hr.card.financial.view') || hasPerm('hr.card.personal.view') || hasPerm('hr.card.certs.view')),
  });

  const title = data?.full_name || 'Карточка сотрудника';
  const subtitle = [data?.position?.title, data?.department?.name]
    .filter(Boolean)
    .join(' · ');

  if (levelLoading || isLoading) {
    return (
      <HRLayout title="Карточка сотрудника" subtitle="">
        <div className="rounded-2xl border bg-card/70 p-8 text-center">
          Загрузка...
        </div>
      </HRLayout>
    );
  }

  if (!hasHrAccess) {
    return (
      <HRLayout title="Карточка сотрудника" subtitle="">
        <div className="rounded-2xl border bg-card/70 p-8 text-center text-muted-foreground">
          Недостаточно прав для HR-раздела
        </div>
      </HRLayout>
    );
  }

  if (error || !data) {
    return (
      <HRLayout title="Карточка сотрудника" subtitle="">
        <div className="rounded-2xl border bg-card/70 p-8 text-center text-destructive">
          Не удалось загрузить карточку.{' '}
          <Link className="underline" to="/hr/employees">
            Назад к списку
          </Link>
        </div>
      </HRLayout>
    );
  }

  return (
    <>
      <HRLayout title={title} subtitle={subtitle}>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => navigate('/hr/employees')}
            className="gap-1.5"
          >
            <ArrowLeft className="h-4 w-4" />
            Назад
          </Button>
          <div className="ml-auto flex flex-wrap gap-2">
            {canWriteBasic && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => navigate(`/hr/employees?edit=${data.id}`)}
                className="gap-1.5"
              >
                <Pencil className="h-4 w-4" />
                Редактировать
              </Button>
            )}
            <Button size="sm" onClick={() => setShareOpen(true)} className="gap-1.5">
              <Share2 className="h-4 w-4" />
              Поделиться
            </Button>
          </div>
        </div>

        <EmployeeCardView card={data} mode="auth" />

        {hasPerm('hr.card.financial.view') && cardT2?.financial && (
          <section className="rounded-lg border p-4">
            <h3 className="font-semibold mb-2">Финансы</h3>
            <div className="text-sm">Оклад: {cardT2.financial.salary ?? '—'}</div>
            <div className="text-sm">Премия: {cardT2.financial.bonus ?? '—'}</div>
            <div className="text-sm">Счёт: {cardT2.financial.bank_account ?? '—'}</div>
          </section>
        )}
        {hasPerm('hr.card.personal.view') && cardT2?.personal && (
          <section className="rounded-lg border p-4">
            <h3 className="font-semibold mb-2">Личные данные</h3>
            <div className="text-sm">Паспорт: {cardT2.personal.passport_data ?? '—'}</div>
            <div className="text-sm">ИНН: {cardT2.personal.inn ?? '—'}</div>
            <div className="text-sm">Дата рождения: {cardT2.personal.birth_date ?? '—'}</div>
            <div className="text-sm">Место рождения: {cardT2.personal.birth_place ?? '—'}</div>
            <div className="text-sm">Гражданство: {cardT2.personal.citizenship ?? '—'}</div>
          </section>
        )}
        {hasPerm('hr.card.certs.view') && cardT2?.certs && (
          <section className="rounded-lg border p-4">
            <h3 className="font-semibold mb-2">Сертификаты / СРО</h3>
            <div className="text-sm">СРО №: {cardT2.certs.sro_permit_number ?? '—'} (до {cardT2.certs.sro_permit_expiry ?? '—'})</div>
            <div className="text-sm">Охрана труда №: {cardT2.certs.safety_cert_number ?? '—'} (до {cardT2.certs.safety_cert_expiry ?? '—'})</div>
          </section>
        )}
      </HRLayout>

      <ShareEmployeeDialog
        open={shareOpen}
        employee={data}
        onClose={() => setShareOpen(false)}
      />
    </>
  );
};

export default HREmployeeCard;
