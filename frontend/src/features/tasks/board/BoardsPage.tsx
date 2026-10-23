/**
 * Страница доски: `/tasks/board` (личная), `/tasks/board/department/:id`,
 * `/tasks/board/project/:id` (мастер-план §7.3, этап S1). Шапка, холст с
 * колонками, фильтр в адресе, быстрая правка и настройки колонок. Карточка
 * пока открывается страницей задачи; окно карточки (`?card=`) — этап S2.
 */
import { useCallback, useMemo, useRef, useState } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

import { Header } from '@/components/Header';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { usePermissions } from '@/hooks/usePermissions';
import { errorStatus, explainedDetail } from '@/lib/apiError';
import type { TaskStatus } from '@/types/tasks';

import { BoardCanvas } from './BoardCanvas';
import { BoardHeader } from './BoardHeader';
import { boardKeyFromPath } from './boardRoutes';
import { BoardSettingsDialog } from './BoardSettingsDialog';
import { canvasStyle } from './boardColors';
import { CardQuickEdit } from './CardQuickEdit';
import { FilterDrawer } from './FilterDrawer';
import {
  useBoard, useLoadMoreColumn, useMoveCard, useQuickAdd, useRenameCard, useSaveColumns,
} from './hooks/useBoard';
import { useBoardFilters } from './hooks/useBoardFilters';
import type { BoardCard, BoardColor, BoardKey, CardMember } from './types';

/** Новая задача без прав администратора задач начинается с этих статусов. */
const INITIAL_STATUSES: TaskStatus[] = ['backlog', 'todo'];

function BoardSkeleton() {
  return (
    <div className="flex gap-3 px-4 pt-3" aria-busy="true">
      {[0, 1, 2, 3].map((index) => (
        <div key={index} className="w-[272px] shrink-0 space-y-2 rounded-xl bg-board-column p-2">
          <Skeleton className="h-5 w-32" />
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
      ))}
    </div>
  );
}

function BoardMissing({ notFound, detail }: { notFound: boolean; detail: string | null }) {
  const { t } = useTranslation();
  return (
    <div className="mx-auto mt-16 max-w-md space-y-3 rounded-xl bg-card p-6 text-center shadow-sm">
      <p className="font-medium">
        {notFound
          ? t('tasks.board.notFound', 'Доски нет или она вам не видна')
          : t('tasks.board.loadFailed', 'Доску не удалось загрузить')}
      </p>
      {detail && <p className="text-sm text-muted-foreground">{detail}</p>}
      <Button asChild variant="outline">
        <Link to="/tasks/board">{t('tasks.board.toPersonal', 'К моей доске')}</Link>
      </Button>
    </div>
  );
}

export default function BoardsPage() {
  const location = useLocation();
  const { id } = useParams<{ id?: string }>();
  const boardKey = useMemo(() => boardKeyFromPath(location.pathname, id), [location.pathname, id]);

  if (!boardKey) {
    return (
      <div className="flex min-h-[100dvh] flex-col bg-background">
        <Header />
        <BoardMissing notFound detail={null} />
      </div>
    );
  }
  // Своё состояние у каждой доски: свёрнутые колонки, быстрая правка.
  return <BoardScreen key={`${boardKey.kind}:${'id' in boardKey ? boardKey.id : ''}`}
    boardKey={boardKey} />;
}

function BoardScreen({ boardKey }: { boardKey: BoardKey }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const permissions = usePermissions();
  const elevated = permissions.atLeast('tasks', 'admin');
  const { filters, setFilters, reset, active } = useBoardFilters();
  const { data: board, isLoading, error } = useBoard(boardKey, filters);
  const move = useMoveCard(boardKey, filters);
  const quickAdd = useQuickAdd(boardKey);
  const saveColumns = useSaveColumns(boardKey);
  const loadMore = useLoadMoreColumn(boardKey, filters);
  const rename = useRenameCard(boardKey);
  const [filterOpen, setFilterOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [quick, setQuick] = useState<{ card: BoardCard; anchor: DOMRect } | null>(null);

  // Участники для фильтра — все, кто встречался на этой доске: при
  // включённом фильтре часть карточек скрыта, а выбор не должен исчезать.
  const seenMembers = useRef(new Map<number, CardMember>());
  const members = useMemo(() => {
    for (const column of board?.columns ?? []) {
      for (const card of column.cards) {
        for (const member of card.members) seenMembers.current.set(member.user_id, member);
      }
    }
    return [...seenMembers.current.values()]
      .sort((a, b) => (a.name ?? '').localeCompare(b.name ?? '', 'ru'));
  }, [board]);

  const title = board?.board.title
    ?? (boardKey.kind === 'personal' ? t('tasks.board.personalTitle', 'Мои задачи') : '…');

  const shown = useMemo(() => {
    if (!board || !filters.hideEmpty || active === 0) return board;
    return { ...board, columns: board.columns.filter((column) => column.count > 0) };
  }, [board, filters.hideEmpty, active]);

  const onMove = useCallback((card: BoardCard, status: TaskStatus,
    before: number | null, after: number | null) => {
    move.mutate({ taskId: card.id, body: { status, before_id: before, after_id: after } });
  }, [move]);

  const onOpenCard = useCallback((card: BoardCard) => navigate(`/tasks/${card.id}`), [navigate]);

  const onQuickEdit = useCallback((card: BoardCard, anchor: HTMLElement) => {
    const host = anchor.closest('[data-testid^="board-card-"]') ?? anchor;
    setQuick({ card, anchor: host.getBoundingClientRect() });
  }, []);

  const onAdd = (status: TaskStatus, summary: string) => quickAdd.mutateAsync({
    summary,
    status,
    ...(boardKey.kind === 'department' ? { department_id: boardKey.id } : {}),
    ...(boardKey.kind === 'project' ? { project_id: boardKey.id } : {}),
  });

  const onSetColumn = (status: TaskStatus, change: { color?: BoardColor | null; hidden?: boolean }) => {
    if (!board) return;
    const columns = board.board.settings.columns;
    saveColumns.mutate({ ...columns, [status]: { ...columns[status], ...change } });
  };

  const canCreateIn = (status: TaskStatus) =>
    Boolean(board?.can.create) && (elevated || INITIAL_STATUSES.includes(status));

  const notFound = errorStatus(error) === 404;
  const hiddenColumns = board ? board.columns.filter((column) => column.hidden).length : 0;

  return (
    <div className="flex h-[100dvh] flex-col bg-background">
      <Header />
      <main className="flex min-h-0 flex-1 flex-col pb-16 md:pb-0"
        style={canvasStyle(board?.board.color ?? null)}>
        <BoardHeader
          boardKey={boardKey}
          title={title}
          activeFilters={active}
          hiddenColumns={hiddenColumns}
          canAdmin={Boolean(board?.can.admin)}
          onOpenFilter={() => setFilterOpen(true)}
          onResetFilter={reset}
          onOpenSettings={() => setSettingsOpen(true)}
        />
        {shown && active > 0 && shown.columns.every((column) => column.hidden || column.count === 0) && (
          <p className="px-4 pt-3 text-sm text-muted-foreground">
            {t('tasks.board.filter.nothing', 'Под фильтр не подходит ни одна карточка.')}
          </p>
        )}
        <div className="min-h-0 flex-1">
          {isLoading && <BoardSkeleton />}
          {!isLoading && error && !board && (
            <BoardMissing notFound={notFound} detail={notFound ? null : explainedDetail(error)} />
          )}
          {shown && (
            <BoardCanvas
              board={shown}
              storageKey={`${boardKey.kind}:${'id' in boardKey ? boardKey.id : 'me'}`}
              onMove={onMove}
              onOpenCard={onOpenCard}
              onQuickEdit={onQuickEdit}
              onAdd={onAdd}
              addPending={quickAdd.isPending}
              canCreateIn={canCreateIn}
              onSetColumn={onSetColumn}
              onLoadMore={(status, offset) => loadMore.mutate({ status, offset })}
            />
          )}
        </div>
      </main>

      <FilterDrawer
        open={filterOpen}
        onOpenChange={setFilterOpen}
        filters={filters}
        onChange={setFilters}
        onReset={reset}
        members={members}
        personal={boardKey.kind === 'personal'}
      />
      {board && (
        <BoardSettingsDialog
          open={settingsOpen}
          onOpenChange={setSettingsOpen}
          columns={board.board.settings.columns}
          saving={saveColumns.isPending}
          onSave={(columns) => saveColumns.mutateAsync(columns)}
        />
      )}
      {quick && board && (
        <CardQuickEdit
          card={quick.card}
          anchor={quick.anchor}
          columns={board.columns}
          onClose={() => setQuick(null)}
          onOpen={onOpenCard}
          onMove={(card, status) => onMove(card, status, null, null)}
          onRename={(card, summary) => rename.mutate({ taskId: card.id, summary })}
        />
      )}
    </div>
  );
}
