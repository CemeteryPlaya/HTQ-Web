/** `/signoff/routes/:id` — страница редактора маршрута.
 *
 * Сам редактор живёт в `components/signoff/RouteEditorPanel`: он же
 * встроен в конструктор шаблона «Запросов», где маршрут задан областью
 * шаблона. Здесь остаётся только рамка раздела и путь назад.
 */

import { Link, useParams } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';

import { RouteEditorPanel } from '@/components/signoff/RouteEditorPanel';
import { SignoffShell } from '@/components/signoff/SignoffShell';

const RouteEditor = () => {
  const { id } = useParams<{ id: string }>();
  return (
    <SignoffShell>
      <Link
        to="/signoff/routes"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors mb-4"
      >
        <ArrowLeft className="h-4 w-4" />
        Ко всем маршрутам
      </Link>
      <RouteEditorPanel routeId={Number(id)} />
    </SignoffShell>
  );
};

export default RouteEditor;
