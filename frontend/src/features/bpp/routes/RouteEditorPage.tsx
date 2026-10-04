/** `/bpp/routes/:id` — редактор маршрута документа модуля: общий
 * `RouteEditorPanel` (он же на `/signoff/routes/:id` и в конструкторе
 * шаблона «Запросов») и путь назад к списку раздела. */
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { RouteEditorPanel } from '@/components/signoff/RouteEditorPanel';

export default function RouteEditorPage() {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();
  return (
    <section className="space-y-4">
      <Link
        to="/bpp/routes"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
      >
        <ArrowLeft className="h-4 w-4" />
        {t('bpp.routes.back', 'Ко всем маршрутам')}
      </Link>
      <RouteEditorPanel routeId={Number(id)} />
    </section>
  );
}
