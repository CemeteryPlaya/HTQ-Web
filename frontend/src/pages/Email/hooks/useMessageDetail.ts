import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { emailApi } from '@/api/email';
import type { EmailMessageDetail } from '@/pages/Email/types';

export function useMessageDetail(messageId: string | null) {
  return useQuery<EmailMessageDetail>({
    queryKey: ['email', 'message', messageId] as const,
    queryFn: () => emailApi.getMessage(messageId as string),
    enabled: !!messageId,
    staleTime: 60_000,
  });
}

export function useMarkRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: emailApi.markAsRead,
    onSuccess: (_, messageId) => {
      qc.invalidateQueries({ queryKey: ['email', 'folder'] });
      qc.invalidateQueries({ queryKey: ['email', 'unread'] });
      qc.invalidateQueries({ queryKey: ['email', 'message', messageId] });
    },
  });
}
