import React from 'react';
import { useTranslation } from 'react-i18next';
import HRLayout from '@/components/hr/HRLayout';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import HRVacancies from './HRVacancies';
import HRApplications from './HRApplications';
import HROffers from './HROffers';

const HRRecruitment = () => {
    const { t } = useTranslation();

    return (
        <HRLayout title={t('hr.pages.recruitment.title')} subtitle={t('hr.pages.recruitment.subtitle')}>
            <Tabs defaultValue="vacancies" className="w-full">
                <TabsList className="mb-6 grid w-full grid-cols-3">
                    <TabsTrigger value="vacancies">{t('hr.nav.vacancies')}</TabsTrigger>
                    <TabsTrigger value="applications">{t('hr.nav.applications')}</TabsTrigger>
                    <TabsTrigger value="offers">{t('hr.nav.offers')}</TabsTrigger>
                </TabsList>
                <TabsContent value="vacancies">
                    <HRVacancies />
                </TabsContent>
                <TabsContent value="applications">
                    <HRApplications />
                </TabsContent>
                <TabsContent value="offers">
                    <HROffers />
                </TabsContent>
            </Tabs>
        </HRLayout>
    );
};

export default HRRecruitment;
