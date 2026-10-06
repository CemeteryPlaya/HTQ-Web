/**
 * Подмодуль «Проекты» — платформенная аппка `project` (D-02) в разделе
 * «Закупки и оплаты»: на проект ссылаются бюджет и документы модуля.
 *
 * Виден при `project:read` — гейт ручек `/api/project/v1` тот же. Какие
 * проекты видны, решает сервер (ПМ — только проекты-участия); создание,
 * правка и участники — узлы `project.projects` и `project.members`,
 * их проверяют экраны и сервер.
 */
import { lazy } from 'react';
import { FolderKanban } from 'lucide-react';

import type { BppGatedModule } from '../core/moduleAccess';

export const bppModule: BppGatedModule = {
  key: 'projects',
  // В меню ТЗ §05 проектов нет — после справочников (90, 91), перед
  // документами без пункта меню (900+).
  order: 95,
  menu: {
    labelKey: 'bpp.projects.title',
    labelFallback: 'Проекты',
    path: 'projects',
    icon: FolderKanban,
  },
  visible: (permissions) => permissions.atLeast('project', 'read'),
  routes: [
    { path: 'projects', element: lazy(() => import('./ProjectsPage')) },
    // Справочник проектных ролей (узел `project.roles`) — до `projects/:id`.
    { path: 'projects/roles', element: lazy(() => import('./ProjectRolesPage')) },
    { path: 'projects/:id', element: lazy(() => import('./ProjectCardPage')) },
  ],
};
