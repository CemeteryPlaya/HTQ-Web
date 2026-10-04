/**
 * Подмодули раздела «Закупки и оплаты» подключаются сами (план этапа 2 A,
 * задача 2 — то же решение, что у бэкендового `models/__init__.py` и
 * `urls.py`): каждый подкаталог `features/bpp/<модуль>/module.tsx` несёт
 * свой пункт меню и свои маршруты, а этот файл их только собирает.
 *
 * Модуль без экспорта `bppModule` — ошибка сборки, а не молчаливый
 * пропуск: раздел без меню или без маршрутов незаметно ломает навигацию,
 * и лучше упасть на старте, чем оставить пункт меню, ведущий в никуда.
 *
 * Пока в пакете нет ни одного `module.tsx` — `bppModules` пуст, это
 * нормально (каркас раздела и первые подмодули заводит отдельная задача).
 */
import type { ComponentType } from 'react';
import type { LucideIcon } from 'lucide-react';

/** Пункт меню раздела «Закупки и оплаты» для одного подмодуля. */
export interface BppMenuItem {
  /** i18n-ключ и запасная подпись (в проекте всюду `t(key, fallback)`). */
  labelKey: string;
  labelFallback: string;
  /** Путь ВНУТРИ раздела, без базового `/bpp` (например `budgets`). */
  path: string;
  icon?: LucideIcon;
}

/** Один маршрут подмодуля — путь внутри раздела и его экран. */
export interface BppRoute {
  /** Путь ВНУТРИ раздела (React Router, относительно `/bpp`). */
  path: string;
  element: ComponentType;
}

/** Манифест подмодуля — то, что экспортирует его `module.tsx`. */
export interface BppModule {
  /** Стабильный ключ — имя подкаталога подмодуля. */
  key: string;
  /** Порядок в меню раздела; при равенстве — по алфавиту `key`. */
  order: number;
  /** Пункт меню раздела. Не у каждого подмодуля есть свой пункт (часть
   * маршрутов открывается только из карточки другого документа). */
  menu?: BppMenuItem;
  routes: BppRoute[];
}

/** То, что должен экспортировать `module.tsx` подмодуля. */
export interface BppModuleExports {
  bppModule?: BppModule;
}

/**
 * Собирает манифесты подмодулей из результата `import.meta.glob` в
 * стабильном порядке: по `order`, а при совпадении — по `key`. Модуль без
 * `bppModule` — ошибка, а не пропуск: путь к файлу попадает в сообщение,
 * чтобы автор сразу видел, какой подкаталог забыл экспорт.
 */
export function collectModules(loaded: Record<string, BppModuleExports>): BppModule[] {
  const collected: BppModule[] = [];
  for (const [path, mod] of Object.entries(loaded)) {
    if (!mod.bppModule) {
      throw new Error(`Подмодуль bpp "${path}" не экспортирует bppModule`);
    }
    collected.push(mod.bppModule);
  }
  return collected.sort((a, b) => a.order - b.order || a.key.localeCompare(b.key));
}

const loadedModules = import.meta.glob<BppModuleExports>('./*/module.tsx', { eager: true });

/** Манифесты всех подмодулей раздела, в порядке показа в меню. */
export const bppModules: BppModule[] = collectModules(loadedModules);
