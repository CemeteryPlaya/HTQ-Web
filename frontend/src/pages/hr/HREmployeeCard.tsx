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
import { useState, type ReactNode } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, Pencil, Share2 } from 'lucide-react';

import { fetchEmployeeCard, fetchCardT2, type CardT2Section } from '@/api/hr';
import HRLayout from '@/components/hr/HRLayout';
import { EmployeeCardView } from '@/components/hr/EmployeeCardView';
import { ShareEmployeeDialog } from '@/components/hr/ShareEmployeeDialog';
import { CardT2SectionDialog } from '@/components/hr/CardT2SectionDialog';
import { Button } from '@/components/ui/button';
import { useHRLevel } from '@/hooks/useHRLevel';

/** Строка «подпись — значение» внутри секции Т-2. */
const Row = ({ label, value }: { label: string; value?: string | null }) => (
  <div className="flex gap-2 text-sm">
    <span className="text-muted-foreground">{label}:</span>
    <span>{value ?? '—'}</span>
  </div>
);

/** Секция Т-2 с кнопкой правки. Кнопка появляется только по edit-ключу —
 *  без него секция остаётся read-only, как и была. */
const T2Section = ({
  title, canEdit, onEdit, children,
}: {
  title: string;
  canEdit: boolean;
  onEdit: () => void;
  children: ReactNode;
}) => (
  <section className="rounded-lg border p-4">
    <div className="mb-2 flex items-center justify-between gap-2">
      <h3 className="font-semibold">{title}</h3>
      {canEdit && (
        <Button variant="ghost" size="sm" onClick={onEdit} className="gap-1.5">
          <Pencil className="h-3.5 w-3.5" />
          Изменить
        </Button>
      )}
    </div>
    <div className="grid gap-1">{children}</div>
  </section>
);

const HREmployeeCard = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const employeeId = Number(id);
  const { hasHrAccess, canWriteBasic, hasPerm, isLoading: levelLoading } = useHRLevel();
  const [shareOpen, setShareOpen] = useState(false);
  // Какую секцию Т-2 сейчас правим; null — диалог закрыт.
  const [editingSection, setEditingSection] = useState<CardT2Section | null>(null);

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

        {/* Секции Т-2. Условие — ПРАВО, а не наличие данных: у сотрудника,
            заведённого без карточки, бэкенд возвращает секцию со всеми null,
            и проверка на данные прятала бы саму возможность их завести
            (строку `EmployeeCard` создаёт upsert при первом сохранении). */}
        {hasPerm('hr.card.financial.view') && (
          <T2Section
            title="Финансы"
            canEdit={hasPerm('hr.card.financial.edit')}
            onEdit={() => setEditingSection('financial')}
          >
            <Row label="Оклад" value={cardT2?.financial?.salary} />
            <Row label="Премия" value={cardT2?.financial?.bonus} />
            <Row label="Счёт" value={cardT2?.financial?.bank_account} />
          </T2Section>
        )}
        {hasPerm('hr.card.personal.view') && (
          <T2Section
            title="Личные данные"
            canEdit={hasPerm('hr.card.personal.edit')}
            onEdit={() => setEditingSection('personal')}
          >
            <Row label="Паспорт" value={cardT2?.personal?.passport_data} />
            <Row label="ИИН/ИНН" value={cardT2?.personal?.inn} />
            <Row label="Дата рождения" value={cardT2?.personal?.birth_date} />
            <Row label="Место рождения" value={cardT2?.personal?.birth_place} />
            <Row label="Гражданство" value={cardT2?.personal?.citizenship} />
          </T2Section>
        )}
        {hasPerm('hr.card.certs.view') && (
          <T2Section
            title="Сертификаты / СРО"
            canEdit={hasPerm('hr.card.certs.edit')}
            onEdit={() => setEditingSection('certs')}
          >
            <Row label="СРО №" value={cardT2?.certs?.sro_permit_number} />
            <Row label="СРО действует до" value={cardT2?.certs?.sro_permit_expiry} />
            <Row label="Охрана труда №" value={cardT2?.certs?.safety_cert_number} />
            <Row label="ОТ действует до" value={cardT2?.certs?.safety_cert_expiry} />
          </T2Section>
        )}
      </HRLayout>

      <ShareEmployeeDialog
        open={shareOpen}
        employee={data}
        onClose={() => setShareOpen(false)}
      />

      {editingSection && (
        <CardT2SectionDialog
          employeeId={employeeId}
          section={editingSection}
          values={cardT2?.[editingSection] as Record<string, string | null> | undefined}
          open
          onClose={() => setEditingSection(null)}
        />
      )}
    </>
  );
};

export default HREmployeeCard;
