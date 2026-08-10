import type { ReactNode } from 'react';
import type { LucideIcon } from 'lucide-react';

import { Skeleton } from '@/components/ui/skeleton';

type CollectionPageHeaderProps = {
  icon: LucideIcon;
  title: string;
  description?: string;
  actions?: ReactNode;
  children?: ReactNode;
};

export function CollectionPageHeader({
  icon: Icon,
  title,
  description,
  actions,
  children,
}: CollectionPageHeaderProps) {
  return (
    <div className="mb-6 space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 items-start gap-3">
          <div className="rounded-lg border bg-muted/50 p-2 text-muted-foreground">
            <Icon className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <h1 className="text-3xl font-bold tracking-tight">{title}</h1>
            {description && (
              <p className="mt-1 text-sm text-muted-foreground">{description}</p>
            )}
          </div>
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </div>
      {children}
    </div>
  );
}

type CollectionTableProps = {
  isLoading: boolean;
  isError: boolean;
  isEmpty: boolean;
  errorMessage: string;
  emptyMessage: string;
  emptyAction?: ReactNode;
  children: ReactNode;
};

export function CollectionTable({
  isLoading,
  isError,
  isEmpty,
  errorMessage,
  emptyMessage,
  emptyAction,
  children,
}: CollectionTableProps) {
  return (
    <div className="overflow-hidden rounded-lg border bg-card">
      {isLoading ? (
        <div className="space-y-3 p-6">
          {[0, 1, 2].map((row) => (
            <Skeleton key={row} className="h-10 w-full" />
          ))}
        </div>
      ) : isError ? (
        <p className="p-6 text-sm text-destructive">{errorMessage}</p>
      ) : isEmpty ? (
        <div className="flex min-h-48 flex-col items-center justify-center p-8 text-center">
          <p className="text-muted-foreground">{emptyMessage}</p>
          {emptyAction && <div className="mt-4">{emptyAction}</div>}
        </div>
      ) : (
        <div className="overflow-x-auto">{children}</div>
      )}
    </div>
  );
}
