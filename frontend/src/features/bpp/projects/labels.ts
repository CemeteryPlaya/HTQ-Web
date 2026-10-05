/**
 * Подписи «Проекта»: вид и статус (`ProjectKind`/`ProjectStatus` сервера).
 * Словаря статусов проекта в `core/statusDictionaries.ts` нет — проект не
 * документ модуля, а справочная сущность платформенной аппки `project`,
 * поэтому тон бейджа задан здесь.
 */
import type { TFunction } from 'i18next';

import type { ProjectKind, ProjectStatus } from './api';

export const KIND_LABELS: Record<ProjectKind, [string, string]> = {
  project: ['bpp.projects.kind.project', 'Проект'],
  company_overhead: ['bpp.projects.kind.company_overhead', 'Общие расходы компании'],
};

export const STATUS_LABELS: Record<ProjectStatus, [string, string, string]> = {
  active: [
    'bpp.projects.status.active', 'Активен',
    'border-transparent bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200',
  ],
  closed: ['bpp.projects.status.closed', 'Закрыт', 'border-transparent bg-muted text-muted-foreground'],
  archived: ['bpp.projects.status.archived', 'Архив', 'border-transparent bg-muted text-muted-foreground'],
};

export const projectKindLabel = (t: TFunction, kind: string): string => {
  const known = KIND_LABELS[kind as ProjectKind];
  return known ? t(known[0], known[1]) : kind;
};
