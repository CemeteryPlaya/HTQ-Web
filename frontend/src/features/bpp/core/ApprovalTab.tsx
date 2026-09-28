/**
 * Вкладка «Согласование» формы документа (ТЗ §05): список кругов
 * согласования (`SubjectProcesses`) и ход последнего из них
 * (`ProcessTimeline`) — компоненты движка signoff, как в его карточке.
 *
 * Процесс адресуется парой `(subject_type, id документа)`; ключ запроса тот
 * же, что у `SubjectProcesses`, поэтому список процессов приходит одним
 * запросом на оба блока.
 */
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import { signoffApi } from '@/api/signoff';
import { ProcessTimeline } from '@/components/signoff/ProcessTimeline';
import { SubjectProcesses } from '@/components/signoff/SubjectProcesses';
import { labelMap } from '@/components/signoff/labels';

export function ApprovalTab({ subjectType, subjectId }: { subjectType: string; subjectId: string }) {
  const { t } = useTranslation();
  const { data: processes = [] } = useQuery({
    queryKey: ['signoff', 'processes', { subjectType, subjectId }],
    queryFn: () =>
      signoffApi
        .listProcesses({ subject_type: subjectType, subject_id: subjectId })
        .then((r) => r.data),
  });
  const { data: enums } = useQuery({
    queryKey: ['signoff', 'enums'],
    queryFn: () => signoffApi.getEnums().then((r) => r.data),
  });
  // Последний круг — с наибольшим id: возвращённый на доработку и снова
  // отправленный документ имеет несколько процессов.
  const latest = processes.reduce<(typeof processes)[number] | null>(
    (best, process) => (best === null || process.id > best.id ? process : best),
    null,
  );

  return (
    <div className="space-y-4">
      <SubjectProcesses subjectType={subjectType} subjectId={subjectId} />
      {latest && (
        <div>
          <h3 className="mb-3 text-base font-semibold">
            {t('bpp.document.progress', 'Ход согласования')}
          </h3>
          <ProcessTimeline
            process={latest}
            stageStateLabels={labelMap(enums?.stage_state)}
            taskStateLabels={labelMap(enums?.task_state)}
          />
        </div>
      )}
    </div>
  );
}
