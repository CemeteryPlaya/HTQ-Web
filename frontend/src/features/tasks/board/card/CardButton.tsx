/**
 * Серая кнопка окна карточки (как в Trello): «Метки», «Даты», «Чек-лист»,
 * «Показать подробности» и прочие действия окна не спорят по цвету с главной
 * кнопкой. `secondary` темы — янтарный акцент, для ряда кнопок он слишком
 * громкий. Ссылка пробрасывается: кнопка служит триггером всплывающих окон.
 */
import { forwardRef } from 'react';

import { Button, type ButtonProps } from '@/components/ui/button';
import { cn } from '@/lib/utils';

export const CardButton = forwardRef<HTMLButtonElement, ButtonProps>(({ className, ...props }, ref) => (
  <Button ref={ref} variant="ghost" size="sm"
    className={cn('bg-muted text-foreground hover:bg-muted/70 hover:text-foreground', className)} {...props} />
));
CardButton.displayName = 'CardButton';
