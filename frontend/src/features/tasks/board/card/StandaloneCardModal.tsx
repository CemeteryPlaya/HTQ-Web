/**
 * Окно карточки вне доски — для старого реестра «Задачи» (`HRTasks`,
 * `EmployeeTasks`), пока он не уступит место доскам (этап S6): то же окно по
 * `?card=<id>`, что на досках, «назад» и Esc закрывают. Колонки — статусы со
 * своими названиями, перенос из окна — сменой статуса задачи.
 */
import { TASK_STATUS_ORDER } from '@/lib/tasks/status';
import type { TaskStatus } from '@/types/tasks';

import { CardModal } from './CardModal';
import { useCardParam, useQuickCardEdit } from './hooks';

const COLUMNS = TASK_STATUS_ORDER.map((status) => ({ status, title: null, color: null, hidden: false }));

function OpenCard({ taskId, onClose }: { taskId: number; onClose: () => void }) {
  const quickEdit = useQuickCardEdit();
  const onMove = (task: { id: number }, status: TaskStatus) =>
    quickEdit.status.mutate({ taskId: task.id, status });
  return <CardModal taskId={taskId} columns={COLUMNS} onClose={onClose} onMove={onMove} />;
}

/** Ставится на страницу один раз; открывает окно `useCardParam().open(id)`. */
export function StandaloneCardModal() {
  const { cardId, close } = useCardParam();
  return cardId ? <OpenCard taskId={cardId} onClose={close} /> : null;
}
