/**
 * Standalone-обёртки вкладок рекрутинга для ПРЯМЫХ маршрутов
 * /hr/vacancies, /hr/applications, /hr/offers.
 *
 * Сами компоненты (HRVacancies / HRApplications / HROffers) — фрагменты без
 * какой-либо обвязки: как вкладки внутри HRRecruitment (/hr/recruitment) они
 * получают Header/Footer/ссылку «Назад в профиль» от его HRLayout. Но те же
 * компоненты зарегистрированы и ОТДЕЛЬНЫМИ маршрутами — по прямому URL
 * открывался голый фрагмент посреди пустой страницы: без шапки, навигации и
 * пути назад. Обернуть их в HRLayout внутри самих файлов нельзя — тогда на
 * /hr/recruitment layout задвоился бы. Отсюда эти обёртки: роутер
 * (lazyPages.ts) указывает сюда, HRRecruitment продолжает импортировать
 * голые фрагменты.
 */
import React from 'react';
import { useTranslation } from 'react-i18next';
import HRLayout from '@/components/hr/HRLayout';
import HRVacancies from './HRVacancies';
import HRApplications from './HRApplications';
import HROffers from './HROffers';

export const HRVacanciesPage: React.FC = () => {
    const { t } = useTranslation();
    return (
        <HRLayout title={t('hr.nav.vacancies')} subtitle={t('hr.pages.recruitment.subtitle')}>
            <HRVacancies />
        </HRLayout>
    );
};

export const HRApplicationsPage: React.FC = () => {
    const { t } = useTranslation();
    return (
        <HRLayout title={t('hr.nav.applications')} subtitle={t('hr.pages.recruitment.subtitle')}>
            <HRApplications />
        </HRLayout>
    );
};

export const HROffersPage: React.FC = () => {
    const { t } = useTranslation();
    return (
        <HRLayout title={t('hr.nav.offers')} subtitle={t('hr.pages.recruitment.subtitle')}>
            <HROffers />
        </HRLayout>
    );
};
