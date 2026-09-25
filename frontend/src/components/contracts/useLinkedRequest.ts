/**
 * Состояние связи «документ ↔ заявка на закуп» для форм договора и счёта.
 *
 * Отдаёт `line` — строку бюджета заявки среди строк, которые форма и так
 * загрузила; страница по ней выставляет свой каскад «администратор →
 * программа → год» и запирает его. `missing` — заявка есть, а строки в
 * списке нет (бюджет не согласован или закрыт): документ всё равно не
 * пройдёт (бэкенд ответит 409), и лучше сказать об этом до отправки.
 */

import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';

import { contractsApi } from '@/api/contracts';
import type { BudgetLineFlat, LinkedRequest } from '@/types/contracts';

export function useLinkedRequest(lines: BudgetLineFlat[]) {
  const [searchParams] = useSearchParams();
  const fromUrl = Number(searchParams.get('request_id')) || null;
  const [linked, setLinked] = useState<LinkedRequest | null>(null);

  const preset = useQuery({
    queryKey: ['contracts', 'linked-request', fromUrl],
    queryFn: () => contractsApi.getLinkedRequest(fromUrl as number).then((r) => r.data),
    enabled: fromUrl != null,
    retry: false,
  });
  useEffect(() => {
    if (preset.data) setLinked(preset.data);
  }, [preset.data]);

  const line = useMemo(
    () => (linked?.budget_line_id != null
      ? lines.find((row) => row.id === linked.budget_line_id) ?? null
      : null),
    [lines, linked],
  );
  const missing = Boolean(linked && lines.length > 0 && !line);

  return { linked, setLinked, line, missing, presetFailed: preset.isError };
}
