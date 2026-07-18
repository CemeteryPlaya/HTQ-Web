import React from 'react';
import { useTranslation } from 'react-i18next';
import {
  Inbox,
  Send,
  FileText,
  Trash2,
  Archive,
  AlertOctagon,
  type LucideIcon,
} from 'lucide-react';
import type { Folder } from '@/pages/Email/types';

interface Props {
  active: Folder;
  onSelect: (folder: Folder) => void;
  unreadByFolder: Record<string, number>;
}

interface Item {
  id: Folder;
  labelKey: string;
  fallback: string;
  icon: LucideIcon;
}

const ITEMS: Item[] = [
  { id: 'inbox', labelKey: 'email.folders.inbox', fallback: 'Входящие', icon: Inbox },
  { id: 'sent', labelKey: 'email.folders.sent', fallback: 'Отправленные', icon: Send },
  { id: 'drafts', labelKey: 'email.folders.drafts', fallback: 'Черновики', icon: FileText },
  { id: 'archive', labelKey: 'email.folders.archive', fallback: 'Архив', icon: Archive },
  { id: 'spam', labelKey: 'email.folders.spam', fallback: 'Спам', icon: AlertOctagon },
  { id: 'trash', labelKey: 'email.folders.trash', fallback: 'Корзина', icon: Trash2 },
];

export const FolderList: React.FC<Props> = ({ active, onSelect, unreadByFolder }) => {
  const { t } = useTranslation();
  return (
    <nav className="flex flex-col gap-1">
      {ITEMS.map((item) => {
        const Icon = item.icon;
        const isActive = active === item.id;
        const unread = unreadByFolder[item.id] || 0;
        return (
          <button
            key={item.id}
            type="button"
            onClick={() => onSelect(item.id)}
            className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
              isActive
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:bg-muted hover:text-foreground'
            }`}
          >
            <Icon className="h-4 w-4" />
            <span className="flex-1 text-left">{t(item.labelKey, item.fallback)}</span>
            {unread > 0 && item.id === 'inbox' && (
              <span className="rounded-full bg-primary/15 px-2 py-0.5 text-xs text-primary">
                {unread}
              </span>
            )}
          </button>
        );
      })}
    </nav>
  );
};

export default FolderList;
