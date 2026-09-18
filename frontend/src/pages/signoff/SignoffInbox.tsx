/**
 * «Ждёт меня» — персональная очередь согласований.
 *
 * Бэкенд отдаёт СВОЮ очередь спрашивающего и ничью больше: чужую нельзя
 * запросить ни по какому параметру. Поэтому здесь нет фильтра «по
 * пользователю» — для надзора есть /signoff/processes.
 *
 * В списке только запросы на АКТИВНЫХ этапах. Запрос на этапе, до которого
 * очередь не дошла, в БД существует, но показывать его как «ждёт вас»
 * нельзя — до него может и не дойти.
 *
 * Решать может НАЗВАННЫЙ в маршруте человек — не тот, у кого админский
 * флаг. Поэтому кнопки решения есть у каждой строки этого списка и только
 * этого: попытка решить чужую задачу вернёт 409, а не 403, и админский
 * токен от этого не спасает.
 */

import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import {
  ArrowRight,
  ClipboardCheck,
  Inbox as InboxIcon,
  MessageSquare,
  Paperclip,
} from 'lucide-react';

import { SignoffShell } from '@/components/signoff/SignoffShell';
import { SubjectLink } from '@/components/signoff/SubjectLink';
import { formatMoment } from '@/components/signoff/format';
import { QUORUM_LABELS } from '@/components/signoff/labels';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { signoffApi } from '@/api/signoff';
import { useTranslation } from 'react-i18next';

const SignoffInbox = () => {
  const { t } = useTranslation();

  const {
    data: items = [],
    isLoading,
    isError,
  } = useQuery({
    queryKey: ['signoff', 'inbox'],
    queryFn: () => signoffApi.inbox().then((r) => r.data),
  });

  return (
    <SignoffShell>
      <div className="mb-6 flex items-center gap-3">
        <InboxIcon className="h-7 w-7 text-muted-foreground" />
        <div>
          <h1 className="text-3xl font-bold">{t('signoff.nav.inbox')}</h1>
          <p className="text-sm text-muted-foreground">
            {t('signoff.inbox.subtitle')}
          </p>
        </div>
        {items.length > 0 && (
          <Badge className="ml-auto text-base px-3 py-1">{items.length}</Badge>
        )}
      </div>

      <div className="bg-card rounded-lg border overflow-x-auto">
        {isLoading ? (
          <div className="p-6 space-y-3">
            {[0, 1, 2].map((row) => (
              <Skeleton key={row} className="h-10 w-full" />
            ))}
          </div>
        ) : isError ? (
          <p className="p-6 text-sm text-destructive">
            {t('signoff.inbox.loadError')}
          </p>
        ) : items.length === 0 ? (
          <div className="p-10 text-center">
            <p className="text-muted-foreground">
              {t('signoff.inbox.empty')}
            </p>
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t('signoff.columns.subject')}</TableHead>
                <TableHead>{t('signoff.columns.stage')}</TableHead>
                <TableHead>{t('signoff.columns.submitted')}</TableHead>
                <TableHead className="text-right">{t('signoff.columns.decision')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item) => (
                <TableRow key={item.task_id}>
                  <TableCell>
                    {/* Заголовок ведёт на карточку процесса, а не на сам
                        документ: там и решение, и меню раздела, и документ
                        внутри. */}
                    <SubjectLink
                      title={item.subject_title}
                      url={item.subject_url}
                      subjectType={item.subject_type}
                      subjectId={item.subject_id}
                      processId={item.process_id}
                    />
                  </TableCell>
                  <TableCell>
                    <div>{item.stage_name}</div>
                    <div className="text-xs text-muted-foreground">
                      {/* «Этап 2 из 4» — только когда этапов больше одного:
                          у одноэтапного маршрута это шум. Нужно тому, кто
                          идёт по маршруту несколько шагов подряд — иначе три
                          его задачи по одной заявке неотличимы. */}
                      {item.stage_count > 1 && (
                        <>
                          {t('signoff.inbox.stepOf', { n: item.stage_order, total: item.stage_count })}
                          {' · '}
                        </>
                      )}
                      {QUORUM_LABELS[item.quorum] ?? item.quorum}
                    </div>
                    {/* Про документ человек должен узнать здесь, а не упереться
                        в отказ, уже нажав «согласовать». */}
                    {item.requires_attachment && (
                      <div className="mt-1 flex items-center gap-1 text-xs text-amber-600 dark:text-amber-500">
                        <Paperclip className="h-3 w-3" />
                        {item.file_id ? t('signoff.inbox.documentAttached') : t('signoff.inbox.pdfNeeded')}
                      </div>
                    )}
                    {item.requires_comment && (
                      <div className="mt-1 flex items-center gap-1 text-xs text-amber-600 dark:text-amber-500">
                        <MessageSquare className="h-3 w-3" />
                        нужно пояснение
                      </div>
                    )}
                    {/* Требование к объекту — то, что человек делает на
                        карточке до решения: «нужно: заполнить поставщика». */}
                    {item.requirement_label && (
                      <div className="mt-1 flex items-center gap-1 text-xs text-amber-600 dark:text-amber-500">
                        <ClipboardCheck className="h-3 w-3" />
                        {t('signoff.inbox.needs', { what: item.requirement_label })}
                      </div>
                    )}
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground whitespace-nowrap">
                    {formatMoment(item.created_at)}
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-end">
                      {/* Только «Открыть» — решение принимается в карточке
                          процесса, где видно, ЧТО согласуют. Раньше здесь
                          висело меню с «Согласовать» / «Отклонить»: три
                          необратимых решения в одном клике из списка, не
                          открыв документа. Цена промаха слишком велика —
                          отклонённый объект запирается, и вернуть его может
                          только отдельный возврат на доработку. */}
                      <Button asChild size="sm" variant="outline">
                        <Link to={`/signoff/processes/${item.process_id}`}>
                          {t('signoff.inbox.open')}
                          <ArrowRight className="ml-1.5 h-4 w-4 opacity-70" />
                        </Link>
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>

    </SignoffShell>
  );
};

export default SignoffInbox;
