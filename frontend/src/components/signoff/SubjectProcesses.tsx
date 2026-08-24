/**
 * История согласований одного предметного объекта.
 *
 * Живёт в `components/signoff`, а не в предметной аппке: показываются
 * СТРОКИ движка, и знать их форму — его дело. Предметная страница передаёт
 * только пару `(subject_type, subject_id)`, которой объект и адресуется —
 * никакого FK между аппками для этого не нужно.
 *
 * Почему это отдельный блок, а не одна кнопка «На согласование».
 * `approval_state` объекта — ТЕКУЩЕЕ состояние и ничего не говорит о том,
 * что было раньше. Возвращённый на доработку и отправленный заново объект
 * выглядит по этому полю как любой другой «на согласовании», и без списка
 * процессов человек, открывший карточку, не увидит ни того, что круг уже
 * был, ни замечаний, с которыми его вернули.
 */

import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { signoffApi } from '@/api/signoff';

import { formatMoment } from './format';
import { labelMap } from './labels';
import { ProcessStateBadge } from './states';
import { useTranslation } from 'react-i18next';

interface Props {
  subjectType: string;
  subjectId: number;
}

export function SubjectProcesses({ subjectType, subjectId }: Props) {
  const { t } = useTranslation();
  const {
    data: processes = [],
    isLoading,
    isError,
  } = useQuery({
    queryKey: ['signoff', 'processes', { subjectType, subjectId }],
    queryFn: () =>
      signoffApi
        .listProcesses({ subject_type: subjectType, subject_id: subjectId })
        .then((r) => r.data),
    enabled: Number.isFinite(subjectId),
  });

  const { data: enums } = useQuery({
    queryKey: ['signoff', 'enums'],
    queryFn: () => signoffApi.getEnums().then((r) => r.data),
  });
  const stateLabels = labelMap(enums?.process_state);

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">{t('signoff.history.title')}</CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-10 w-full" />
        ) : isError ? (
          // 503 — модуль согласования выключен целиком. Это не поломка
          // карточки: остальные её блоки читаются и без него.
          <p className="text-sm text-muted-foreground">
            {t('signoff.history.unavailable')}
          </p>
        ) : processes.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {t('signoff.history.neverSubmitted')}
          </p>
        ) : (
          <ul className="divide-y">
            {processes.map((process) => (
              <li
                key={process.id}
                className="flex flex-wrap items-center justify-between gap-2 py-2 first:pt-0 last:pb-0"
              >
                <div className="min-w-0">
                  <Link
                    to={`/signoff/processes/${process.id}`}
                    className="text-sm font-medium hover:underline underline-offset-2"
                  >
                    {t('signoff.history.processNumber', { id: process.id })}
                  </Link>
                  <p className="text-xs text-muted-foreground">
                    {t('signoff.detail.startedAt', { stamp: formatMoment(process.created_at) })}
                    {process.finished_at
                      && t('signoff.history.finishedAt', { stamp: formatMoment(process.finished_at) })}
                  </p>
                </div>
                <ProcessStateBadge
                  state={process.state}
                  label={stateLabels[process.state]}
                />
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
