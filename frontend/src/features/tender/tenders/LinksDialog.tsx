/**
 * Ссылки участников тендера — после публикации, перевыпуска или приглашения
 * в идущий тендер. Сервер хранит только хэш токена, поэтому ссылка видна
 * ОДИН раз: закрыли диалог, не скопировав, — остаётся перевыпуск (старая
 * ссылка перестанет работать). Почтой ссылки уйдут с этапа 4.
 */
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { AlertTriangle, Copy } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';

import { copyText } from '../core/clipboard';

export interface ShownLink {
  invitationId: string;
  name: string;
  email: string;
  link: string;
}

interface Props {
  links: ShownLink[];
  onClose: () => void;
}

export function LinksDialog({ links, onClose }: Props) {
  const { t } = useTranslation();
  const copy = (link: string) => {
    copyText(link).then(
      () => toast.success(t('tender.tenders.linkCopied', 'Ссылка скопирована')),
      () => toast.error(t('tender.tenders.copyFailed', 'Не удалось скопировать — выделите ссылку и скопируйте вручную')),
    );
  };

  return (
    <Dialog open={links.length > 0} onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t('tender.tenders.linksTitle', 'Ссылки для участников')}</DialogTitle>
          <DialogDescription className="flex gap-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-foreground dark:border-amber-800 dark:bg-amber-950/40">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>
              {t(
                'tender.tenders.linksOnce',
                'Ссылки показываются один раз — скопируйте и отправьте их участникам сейчас. Потерянную ссылку можно только перевыпустить: прежняя перестанет работать.',
              )}
            </span>
          </DialogDescription>
        </DialogHeader>
        <ul className="space-y-3">
          {links.map((item) => (
            <li key={item.invitationId} className="space-y-1">
              <div className="text-sm">
                <span className="font-medium">{item.name}</span>
                {item.email && <span className="text-muted-foreground"> · {item.email}</span>}
              </div>
              <div className="flex gap-2">
                <Input
                  readOnly value={item.link} className="font-mono text-xs"
                  aria-label={t('tender.tenders.linkFor', 'Ссылка для {{name}}', { name: item.name })}
                  onFocus={(event) => event.target.select()}
                />
                <Button type="button" variant="outline" onClick={() => copy(item.link)}>
                  <Copy className="mr-1.5 h-4 w-4" />
                  {t('tender.tenders.copy', 'Скопировать')}
                </Button>
              </div>
            </li>
          ))}
        </ul>
        <DialogFooter>
          <Button type="button" onClick={onClose}>{t('tender.tenders.done', 'Готово')}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
