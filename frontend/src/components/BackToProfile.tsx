/**
 * BackToProfile — единственная каноническая ссылка «Назад в профиль».
 *
 * До этого компонента по страницам жили ШЕСТЬ разных вариантов одной и той
 * же ссылки: три текста («Назад в профиль» / «К моему профилю» / «К
 * профилю»), три i18n-ключа (`hr.backToMain`, `tasks.backToMain`,
 * `settingsPage.backToProfile`), четыре страницы с текстом, вшитым в JSX
 * мимо i18n, и три разных вёрстки — каждая новая страница копировала
 * ближайший образец. Теперь образец один: НОВУЮ страницу подключайте через
 * этот компонент, а не копированием `<Link to="/myprofile">`.
 *
 * Вид — «таблетка» из AdminNews (решение пользователя, 2026-07-28): серая
 * пилюля, стрелка уезжает влево при наведении. Ключ перевода —
 * `common.backToProfile` (ru + en в public/locales), инлайновый дефолт
 * держит русский текст на случай отсутствия ресурса.
 */
import React from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';

interface Props {
    /** Дополнительные классы поверх канонических — только про ОТСТУПЫ
     *  (например, `mb-4` вместо дефолтного `mb-8`), не про сам вид. */
    className?: string;
}

export const BackToProfile: React.FC<Props> = ({ className }) => {
    const { t } = useTranslation();
    return (
        <Link
            to="/myprofile"
            className={cn(
                'group mb-8 inline-flex w-fit items-center gap-2 rounded-full bg-muted/70 px-4 py-2 text-sm font-medium text-muted-foreground backdrop-blur-sm transition-all hover:bg-primary/10 hover:text-primary active:scale-95 touch-target shadow-2xs border border-border/40',
                className,
            )}
        >
            <ArrowLeft className="h-4 w-4 transition-transform group-hover:-translate-x-1 text-primary shrink-0" />
            <span>{t('common.backToProfile', 'Назад в профиль')}</span>
        </Link>
    );
};
