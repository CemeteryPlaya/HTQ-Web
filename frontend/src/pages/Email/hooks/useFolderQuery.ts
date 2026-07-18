import { useQuery } from '@tanstack/react-query';
import { emailApi } from '@/api/email';
import type {
  ActiveAccountId,
  EmailMessageSummary,
  Folder,
} from '@/pages/Email/types';

export function useFolderQuery(
  accountId: ActiveAccountId,
  folder: Folder,
  page = 0,
  pageSize = 50,
) {
  return useQuery<EmailMessageSummary[]>({
    queryKey: ['email', 'folder', accountId, folder, page] as const,
    queryFn: () =>
      emailApi.listMessages({
        folder,
        accountId: accountId === 'all' ? null : accountId,
        limit: pageSize,
        offset: page * pageSize,
      }),
    placeholderData: (prev) => prev,
    staleTime: 10_000,
  });
}
