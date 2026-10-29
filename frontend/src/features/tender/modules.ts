/**
 * Подразделы раздела «Тендеры» подключаются сами (T0.4, мастер-план
 * тендерного модуля §3.1 — по образцу `features/bpp/modules.ts`): каждый
 * подкаталог `features/tender/<подраздел>/module.tsx` несёт свой пункт меню
 * и свои маршруты, а этот файл их только собирает.
 *
 * Подраздел без экспорта `tenderModule` — ошибка сборки, а не молчаливый
 * пропуск: раздел без меню или без маршрутов незаметно ломает навигацию.
 *
 * В отличие от БЗО признак видимости (`visible`) — сразу поле манифеста, а
 * не расширение в отдельном файле: у БЗО оно появилось позже реестра.
 */
import type { ComponentType } from 'react';
import type { LucideIcon } from 'lucide-react';

import type { Permissions } from '@/hooks/usePermissions';

/** Базовый путь раздела — пункты меню подразделов относительны ему. */
export const TENDER_BASE = '/tender';

/** Адрес пункта меню подраздела (`requests` → `/tender/requests`). */
export const tenderMenuHref = (path: string): string =>
  `${TENDER_BASE}/${path.replace(/^\/+/, '')}`;

/** Пункт меню раздела «Тендеры» для одного подраздела. */
export interface TenderMenuItem {
  /** i18n-ключ и запасная подпись (в проекте всюду `t(key, fallback)`). */
  labelKey: string;
  labelFallback: string;
  /** Путь ВНУТРИ раздела, без базового `/tender` (например `requests`). */
  path: string;
  icon?: LucideIcon;
}

/** Один маршрут подраздела — путь внутри раздела и его экран. */
export interface TenderRoute {
  /** Путь ВНУТРИ раздела (React Router, относительно `/tender`). */
  path: string;
  element: ComponentType;
}

/** Манифест подраздела — то, что экспортирует его `module.tsx`. */
export interface TenderModule {
  /** Стабильный ключ — имя подкаталога подраздела. */
  key: string;
  /** Порядок в меню раздела; при равенстве — по алфавиту `key`. */
  order: number;
  /** Пункт меню. Не у каждого подраздела он есть (часть экранов
   * открывается только из карточки другого документа). */
  menu?: TenderMenuItem;
  routes: TenderRoute[];
  /**
   * `false` — пункта меню нет, а маршруты подраздела отвечают «Нет
   * доступа». Без поля подраздел виден всякому, кто вошёл в раздел (гейт
   * `/tender/*` — `tender:read`). Права повторно проверяет сервер.
   */
  visible?: (permissions: Permissions) => boolean;
}

/** То, что должен экспортировать `module.tsx` подраздела. */
export interface TenderModuleExports {
  tenderModule?: TenderModule;
}

/** Виден ли подраздел пользователю с этими правами. */
export function tenderModuleVisible(module: TenderModule, permissions: Permissions): boolean {
  return typeof module.visible === 'function' ? module.visible(permissions) : true;
}

/**
 * Собирает манифесты подразделов из результата `import.meta.glob` в
 * стабильном порядке: по `order`, а при совпадении — по `key`. Подраздел
 * без `tenderModule` — ошибка с путём файла в сообщении.
 */
export function collectModules(loaded: Record<string, TenderModuleExports>): TenderModule[] {
  const collected: TenderModule[] = [];
  for (const [path, mod] of Object.entries(loaded)) {
    if (!mod.tenderModule) {
      throw new Error(`Подраздел tender "${path}" не экспортирует tenderModule`);
    }
    collected.push(mod.tenderModule);
  }
  return collected.sort((a, b) => a.order - b.order || a.key.localeCompare(b.key));
}

const loadedModules = import.meta.glob<TenderModuleExports>('./*/module.tsx', { eager: true });

/** Манифесты всех подразделов раздела, в порядке показа в меню. */
export const tenderModules: TenderModule[] = collectModules(loadedModules);
