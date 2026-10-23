/**
 * Цвета колонок доски (решение K-34): палитра из 10 цветов, как в Trello, на
 * токенах темы `--board-color-*` (`index.css`, светлая и тёмная тема).
 */
import type { CSSProperties } from 'react';

import type { BoardColor } from './types';

/** Фон колонки: цвет палитры полупрозрачно поверх холста — подписи
 * читаются в обеих темах; без цвета — нейтральная колонка темы. */
export function columnStyle(color: BoardColor | null): CSSProperties {
  if (!color) return { backgroundColor: 'hsl(var(--board-column))' };
  return {
    backgroundColor: `hsl(var(--board-color-${color}) / 0.28)`,
    boxShadow: `inset 0 3px 0 hsl(var(--board-color-${color}))`,
  };
}

/** Образец цвета в палитре выбора. */
export function swatchStyle(color: BoardColor): CSSProperties {
  return { backgroundColor: `hsl(var(--board-color-${color}))` };
}

/** Фон холста: у доски проекта — цвет проекта, иначе нейтральный градиент. */
export function canvasStyle(projectColor: string | null): CSSProperties {
  if (projectColor) {
    return {
      backgroundImage: `linear-gradient(135deg, ${projectColor}55, ${projectColor}22 55%, hsl(var(--board-canvas-to)))`,
      backgroundColor: 'hsl(var(--board-canvas-to))',
    };
  }
  return {
    backgroundImage: 'linear-gradient(135deg, hsl(var(--board-canvas-from)), hsl(var(--board-canvas-to)))',
  };
}
