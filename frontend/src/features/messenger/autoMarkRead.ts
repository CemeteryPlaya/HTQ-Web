/**
 * Ставить ли отметку «прочитано» автоматически, при открытии чата.
 *
 * Вынесено из `MessengerPage.tsx` чистой функцией, чтобы условие проверялось
 * тестом без монтирования всей страницы мессенджера.
 *
 * Архив компании — только чтение (docs/plans/2026-09-25-archive-read-only-spec.md):
 * на её поддомене любой POST отбивается 403 `company_archived`, а интерцептор
 * `api/client.ts` показывает на него тост «Нельзя изменить…». Автоматический
 * `markRead` — не действие пользователя, и суперпользователь, просто открывший
 * чат в архиве, видел бы этот тост на каждое сообщение. Пока права не
 * загрузились, архив ли это — неизвестно, поэтому ждём ответа `/access/me`:
 * эффект перезапустится, когда флаги сменятся, и отметка в действующей
 * компании уйдёт с задержкой в один запрос, а не потеряется.
 */
export interface AutoMarkReadInput {
    roomId: string | number | null | undefined;
    lastMessageId: string | number | null | undefined;
    companyArchived: boolean;
    permissionsLoading: boolean;
}

export function shouldAutoMarkRead({
    roomId,
    lastMessageId,
    companyArchived,
    permissionsLoading,
}: AutoMarkReadInput): boolean {
    if (!roomId || !lastMessageId) return false;
    return !permissionsLoading && !companyArchived;
}
