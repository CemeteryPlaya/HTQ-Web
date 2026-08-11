import type { ReactNode } from 'react';
import type { LucideIcon } from 'lucide-react';
import { Search } from 'lucide-react';

import { Skeleton } from '@/components/ui/skeleton';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';

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

type CollectionSearchProps = {
  value: string;
  onValueChange: (value: string) => void;
  placeholder: string;
  label?: string;
};

/** A consistent, immediately applied search control for registry pages. */
export function CollectionSearch({
  value,
  onValueChange,
  placeholder,
  label = 'Поиск по списку',
}: CollectionSearchProps) {
  return (
    <div className="relative max-w-md">
      <Search
        aria-hidden="true"
        className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
      />
      <Input
        aria-label={label}
        value={value}
        onChange={(event) => onValueChange(event.target.value)}
        placeholder={placeholder}
        className="pl-9"
      />
    </div>
  );
}

export type Pagination = {
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
};

export function CollectionPagination({
  pagination,
  onPageChange,
  isLoading = false,
}: {
  pagination?: Pagination;
  onPageChange: (page: number) => void;
  isLoading?: boolean;
}) {
  if (!pagination || pagination.total_pages <= 1) return null;

  return (
    <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-sm">
      <p className="text-muted-foreground">
        Показано {(pagination.page - 1) * pagination.page_size + 1}–
        {Math.min(pagination.page * pagination.page_size, pagination.total)} из {pagination.total}
      </p>
      <div className="flex items-center gap-2">
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={isLoading || pagination.page <= 1}
          onClick={() => onPageChange(pagination.page - 1)}
        >
          Назад
        </Button>
        <span className="tabular-nums text-muted-foreground">
          {pagination.page} / {pagination.total_pages}
        </span>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={isLoading || pagination.page >= pagination.total_pages}
          onClick={() => onPageChange(pagination.page + 1)}
        >
          Вперёд
        </Button>
      </div>
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
        <>
          <div className="overflow-x-auto">{children}</div>
          <p className="border-t px-4 py-2 text-xs text-muted-foreground md:hidden">
            Проведите таблицу влево, чтобы увидеть остальные поля и действия.
          </p>
        </>
      )}
    </div>
  );
}
