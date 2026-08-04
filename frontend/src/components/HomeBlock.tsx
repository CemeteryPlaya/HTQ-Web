/**
 * HomeBlock — обёртка секции лендинга, знающая про видимость и порядок из БД.
 *
 * ПОЧЕМУ РЕШЕНИЕ ЗДЕСЬ, А НЕ ВНУТРИ САМИХ СЕКЦИЙ. Ранний `return null` внутри
 * компонента пришлось бы ставить после `useHomeSection`, но ниже в этих
 * компонентах есть свои хуки (счётчики цифр, карусели, IntersectionObserver).
 * Условный выход посреди списка хуков меняет их количество между рендерами —
 * React такое не прощает. Родитель же просто не монтирует ребёнка, и вопрос
 * снимается целиком.
 *
 * Пока список секций не загрузился, блок ПОКАЗЫВАЕТСЯ: иначе лендинг моргал бы
 * пустотой на каждом заходе, а при недоступном бэкенде остался бы пустым.
 */
import type { ReactNode } from 'react';

import { useHomeSection } from '@/hooks/useHomeContent';

export function HomeBlock({
  sectionKey,
  children,
}: {
  sectionKey: string;
  children: ReactNode;
}) {
  const { hidden } = useHomeSection(sectionKey);
  if (hidden) return null;
  return <>{children}</>;
}

export default HomeBlock;
