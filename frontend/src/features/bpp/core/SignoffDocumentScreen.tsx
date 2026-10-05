/**
 * Документ модуля по прямой ссылке (`/bpp/requests/:id`,
 * `/bpp/accountable/:id`) — до экранов B2.5.
 *
 * Сюда ведут ссылки движка согласования и центра уведомлений (колбэк
 * `describe` в `apps/bpp/approval_hooks.py`). Пока у документа нет своей
 * формы на `BppDocumentShell`, раздел показывает то же тело, что карточка
 * согласования, — ровно то, что показывала снятая временная рамка
 * `DocumentPage.tsx`, только внутри раздела с его меню.
 */
import { Suspense, type ComponentType } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';

import { Skeleton } from '@/components/ui/skeleton';

export interface DocumentViewProps {
  id: string;
  embedded?: boolean;
}

export function SignoffDocumentScreen({ view: View }: { view: ComponentType<DocumentViewProps> }) {
  const { t } = useTranslation();
  const { id = '' } = useParams<{ id: string }>();
  return (
    <div>
      <Link
        to="/signoff"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors mb-4"
      >
        <ArrowLeft className="h-4 w-4" />
        {t('bpp.document.toSignoff', 'К согласованиям')}
      </Link>
      <Suspense fallback={<Skeleton className="h-64 w-full" />}>
        <View id={id} />
      </Suspense>
    </div>
  );
}
