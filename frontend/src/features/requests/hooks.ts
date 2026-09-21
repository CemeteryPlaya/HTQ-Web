/** TanStack Query hooks for the Requests feature. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useRef } from 'react';

import { contractsApi } from '@/api/contracts';
import { fetchEmployees } from '@/api/hr';
import { requestsApi } from '@/api/requests';
import { getAccessToken } from '@/lib/auth/profileStorage';

export const QK = {
  inbox: ['requests', 'instances', 'inbox'] as const,
  sent: ['requests', 'instances', 'sent'] as const,
  cc: ['requests', 'instances', 'cc'] as const,
  done: ['requests', 'instances', 'done'] as const,
  instance: (id: number) => ['requests', 'instances', id] as const,
  templates: (projectId?: number | null) => ['requests', 'templates', projectId ?? 'all'] as const,
  template: (id: number) => ['requests', 'templates', id] as const,
  templateVersion: (templateId: number, versionId: number) =>
    ['requests', 'templates', templateId, 'versions', versionId] as const,
  projects: ['requests', 'projects'] as const,
  project: (id: number) => ['requests', 'projects', id] as const,
};

export function useInbox() {
  return useQuery({
    queryKey: QK.inbox,
    queryFn: () => requestsApi.instances.list('inbox'),
  });
}

export function useSent() {
  return useQuery({
    queryKey: QK.sent,
    queryFn: () => requestsApi.instances.list('sent'),
  });
}

/** Копия (CC) — requests the user follows as a watcher. */
export function useCc() {
  return useQuery({
    queryKey: QK.cc,
    queryFn: () => requestsApi.instances.list('cc'),
  });
}

/** Готово (Done) — requests the user has already acted on. */
export function useDone() {
  return useQuery({
    queryKey: QK.done,
    queryFn: () => requestsApi.instances.list('done'),
  });
}

export function useInstance(id: number | null | undefined) {
  return useQuery({
    queryKey: id != null ? QK.instance(id) : ['requests', 'instances', 'none'],
    queryFn: () => requestsApi.instances.get(id as number),
    enabled: id != null,
  });
}

export function useTemplates(projectId?: number | null) {
  return useQuery({
    queryKey: QK.templates(projectId),
    queryFn: () => requestsApi.templates.list(projectId),
  });
}

export function useTemplate(id: number | null | undefined) {
  return useQuery({
    queryKey: id != null ? QK.template(id) : ['requests', 'templates', 'none'],
    queryFn: () => requestsApi.templates.get(id as number),
    enabled: id != null,
  });
}

export function useTemplateVersion(templateId: number | null | undefined, versionId: number | null | undefined) {
  return useQuery({
    queryKey: templateId != null && versionId != null
      ? QK.templateVersion(templateId, versionId)
      : ['requests', 'templates', 'no-version'],
    queryFn: () => requestsApi.templates.getVersion(templateId as number, versionId as number),
    enabled: templateId != null && versionId != null,
  });
}

export function useProjects() {
  return useQuery({ queryKey: QK.projects, queryFn: () => requestsApi.projects.list() });
}

/* ─── reference data sources (Lark Base) ──────────────────────────────── */

export function useReferenceSources() {
  return useQuery({
    queryKey: ['requests', 'reference', 'sources'],
    queryFn: () => requestsApi.reference.list(),
  });
}

/** Template data tables (Управление данными) the current user may access. */
export function useMyDataTables() {
  return useQuery({
    queryKey: ['requests', 'reference', 'my-data-tables'],
    queryFn: () => requestsApi.reference.myDataTables(),
  });
}

export function useReferenceRows(id: number | null | undefined) {
  return useQuery({
    queryKey: ['requests', 'reference', 'rows', id],
    queryFn: () => requestsApi.reference.listRows(id as number),
    enabled: id != null,
  });
}

/** Options for a `reference` widget — distinct values of `column`, optionally
 *  filtered by a parent field (dependent selects). */
export function useReferenceOptions(
  slug?: string, column?: string, filterCol?: string, filterVal?: string,
) {
  return useQuery({
    queryKey: ['requests', 'reference', 'options', slug, column, filterCol, filterVal],
    queryFn: () => requestsApi.reference.options(slug as string, column as string, filterCol, filterVal),
    enabled: Boolean(slug && column),
  });
}

/** Строки бюджета для виджета `budget_line_ref` — тот же плоский список,
 *  что читает форма договора (`GET /api/contracts/v1/budget-lines`).
 *  Раздел «Договоры» может быть выключен (503 `service_disabled`) — это не
 *  ошибка формы, поэтому без повторов; контрол показывает подсказку. */
export function useBudgetLines(enabled = true) {
  return useQuery({
    queryKey: ['contracts', 'budget-lines', 'requests-widget'],
    queryFn: () => contractsApi.listBudgetLines().then((r) => r.data),
    enabled,
    retry: false,
  });
}

/** Map of platform user_id -> employee full name, for resolving picked people
 *  (approvers, CC) to names in the workflow builder. Shares the EmployeePicker
 *  query cache. */
export function useEmployeeNames(): Map<number, string> {
  const q = useQuery({ queryKey: ['hr', 'employees', 'picker'], queryFn: () => fetchEmployees() });
  return useMemo(() => {
    const m = new Map<number, string>();
    for (const e of q.data ?? []) {
      if (e.user_id != null) m.set(e.user_id, e.full_name || `ID ${e.user_id}`);
    }
    return m;
  }, [q.data]);
}

/* ─── Mutations ───────────────────────────────────────────────────────── */

export function useCreateDraft() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: requestsApi.instances.create,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['requests', 'instances'] }),
  });
}

/** Отправка на согласование. Ответ — карточка ПРОЦЕССА signoff, поэтому в
 *  кэш заявки он не кладётся: саму заявку перечитываем — её статус изменил
 *  колбэк движка. */
export function useSubmitInstance(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => requestsApi.instances.submit(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: QK.instance(id) });
      qc.invalidateQueries({ queryKey: ['requests', 'instances'] });
      qc.invalidateQueries({ queryKey: ['signoff'] });
    },
  });
}




/* ─── SSE stream — fan-in real-time updates to the query cache ──────── */

const STREAM_URL = '/api/requests/v1/stream';

/** Open the SSE stream once per logged-in session. Re-invalidates
 *  inbox / sent / instance queries as events arrive. Auto-reconnects via
 *  the native EventSource. */
export function useRequestsStream() {
  const qc = useQueryClient();
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) return;
    const url = `${STREAM_URL}?token=${encodeURIComponent(token)}`;
    const es = new EventSource(url);
    esRef.current = es;

    const onAny = (raw: MessageEvent) => {
      try {
        const data = JSON.parse(raw.data || '{}');
        const requestId: number | undefined = data?.request_id;
        if (requestId) qc.invalidateQueries({ queryKey: QK.instance(requestId) });
      } catch { /* ignore parse errors */ }
      qc.invalidateQueries({ queryKey: ['requests', 'instances'] });
      // Личная сводка считается на сервере и от списков не зависит —
      // её надо обновлять отдельно, иначе «Отправлено мной» и суммы
      // застывают до перезагрузки страницы.
      qc.invalidateQueries({ queryKey: ['requests', 'stats', 'mine'] });
    };

    for (const kind of [
      'request_assigned', 'approved_partial', 'request_changes',
      'rejected', 'approved_final', 'cancelled', 'reminder', 'escalation',
    ]) {
      es.addEventListener(kind, onAny as EventListener);
    }
    es.addEventListener('error', () => {
      // EventSource auto-reconnects with backoff; nothing else to do.
    });

    return () => {
      es.close();
      esRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}
