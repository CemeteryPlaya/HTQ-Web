/**
 * `/tasks` — раздел «Задачи» открывает последнюю открытую доску человека, в
 * первый раз — личную (этап S6a, решение R-03). Параметры адреса переезжают
 * вместе с ним: старые ссылки и уведомления `/tasks?card=<id>` открывают окно
 * карточки поверх доски.
 */
import { Navigate, useLocation } from 'react-router-dom';

import { lastBoardUrl } from './boardRoutes';

export default function TasksHome() {
  const location = useLocation();
  return <Navigate replace to={`${lastBoardUrl()}${location.search}`} />;
}
