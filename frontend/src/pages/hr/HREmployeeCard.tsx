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
import { useTranslation } from 'react-i18next';

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
  const { t } = useTranslation();
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
    enabled: !!employeeId && (hasPerm('hr.card.financial.view') || hasPerm('hr.card.personal.view')),
  });

  const title = data?.full_name || t('share.employee.title');
  const subtitle = [data?.position?.title, data?.department?.name]
    .filter(Boolean)
    .join(' · ');

  if (levelLoading || isLoading) {
    return (
      <HRLayout title={t('share.employee.title')} subtitle="">
        <div className="rounded-2xl border bg-card/70 p-8 text-center">
          {t('common.loading')}
        </div>
      </HRLayout>
    );
  }

  if (!hasHrAccess) {
    return (
      <HRLayout title={t('share.employee.title')} subtitle="">
        <div className="rounded-2xl border bg-card/70 p-8 text-center text-muted-foreground">
          {t('hr.employeeCard.noRights')}
        </div>
      </HRLayout>
    );
  }

  if (error || !data) {
    return (
      <HRLayout title={t('share.employee.title')} subtitle="">
        <div className="rounded-2xl border bg-card/70 p-8 text-center text-destructive">
          {t('hr.employeeCard.loadError')}{' '}
          <Link className="underline" to="/hr/employees">
            {t('hr.employeeCard.backToList')}
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
            {t('common.back')}
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
                {t('common.edit')}
              </Button>
            )}
            <Button size="sm" onClick={() => setShareOpen(true)} className="gap-1.5">
              <Share2 className="h-4 w-4" />
              {t('common.share')}
            </Button>
          </div>
        </div>

        <EmployeeCardView card={data} mode="auth" />

        {/* Секции Т-2. Условие — ПРАВО, а не наличие данных: у сотрудника,
            заведённого без карточки, бэкенд возвращает секцию со всеми null,
            и проверка на данные прятала бы саму возможность их завести
            (строку `EmployeeCard` создаёт upsert при первом сохранении).

            Подписи строк берём из `hr.pages.employees.fields.*` — тех же
            ключей, что и форма редактирования (`cardT2Fields.ts`): иначе
            карточка и форма назвали бы одно поле по-разному.

            Секции «Сертификаты / СРО» здесь больше нет: миграция
            hr/0016_remove_employeecard_certs сняла её колонки, на бэкенде
            остались только financial и personal. */}
        {hasPerm('hr.card.financial.view') && (
          <T2Section
            title={t('hr.employeeCard.finance')}
            canEdit={hasPerm('hr.card.financial.edit')}
            onEdit={() => setEditingSection('financial')}
          >
            <Row label={t('hr.pages.employees.fields.salary')} value={cardT2?.financial?.salary} />
            <Row label={t('hr.pages.employees.fields.bonus')} value={cardT2?.financial?.bonus} />
            <Row label={t('hr.pages.employees.fields.bankAccount')} value={cardT2?.financial?.bank_account} />
          </T2Section>
        )}
        {hasPerm('hr.card.personal.view') && (
          <T2Section
            title={t('hr.employeeCard.personal')}
            canEdit={hasPerm('hr.card.personal.edit')}
            onEdit={() => setEditingSection('personal')}
          >
            <Row label={t('hr.pages.employees.fields.passportData')} value={cardT2?.personal?.passport_data} />
            <Row label={t('hr.pages.employees.fields.inn')} value={cardT2?.personal?.inn} />
            <Row label={t('hr.pages.employees.fields.birthDate')} value={cardT2?.personal?.birth_date} />
            <Row label={t('hr.pages.employees.fields.birthPlace')} value={cardT2?.personal?.birth_place} />
            <Row label={t('hr.pages.employees.fields.citizenship')} value={cardT2?.personal?.citizenship} />
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
