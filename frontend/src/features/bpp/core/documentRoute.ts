/**
 * Экран маршрута «документ по прямой ссылке» для манифеста подмодуля:
 * `routes: [{ path: 'requests/:id', element: documentRoute(() => import('./RequestSignoffView')) }]`.
 *
 * Фабрика — в `.ts`, а не рядом с манифестом: `module.tsx` с локальным
 * компонентом и не-компонентным экспортом `bppModule` ломает fast refresh
 * (правило `react-refresh/only-export-components`). Представление грузится
 * лениво — чанк документа не тянется в раздел, пока его не открыли.
 */
import { createElement, lazy, type ComponentType } from 'react';

import { SignoffDocumentScreen, type DocumentViewProps } from './SignoffDocumentScreen';

export function documentRoute(
  load: () => Promise<{ default: ComponentType<DocumentViewProps> }>,
): ComponentType {
  const View = lazy(load);
  const DocumentRoute = () => createElement(SignoffDocumentScreen, { view: View });
  return DocumentRoute;
}
