/**
 * Бейдж статуса проекта. Словаря проекта в общем `StatusBadge` нет (проект
 * — не документ модуля), поэтому свой; неизвестный код показывается как
 * есть, чтобы новый статус сервера не прятался под чужой подписью.
 */
import { useTranslation } from 'react-i18next';

import { Badge } from '@/components/ui/badge';

import type { ProjectStatus } from './api';
import { STATUS_LABELS } from './labels';

export function ProjectStatusBadge({ status }: { status: string }) {
  const { t } = useTranslation();
  const known = STATUS_LABELS[status as ProjectStatus];
  if (!known) return <Badge variant="outline" className="font-mono font-normal">{status || '—'}</Badge>;
  return <Badge className={known[2]}>{t(known[0], known[1])}</Badge>;
}

export default ProjectStatusBadge;
