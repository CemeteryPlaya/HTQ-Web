import { useQuery } from '@tanstack/react-query';
import { emailApi } from '@/api/email';
import type { UnreadCounts } from '@/pages/Email/types';

export function useUnreadCounts() {
  return useQuery<UnreadCounts>({
    queryKey: ['email', 'unread'],
    queryFn: emailApi.unreadCounts,
    staleTime: 15_000,
  });
}
