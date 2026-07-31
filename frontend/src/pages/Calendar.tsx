import React from 'react';
import { useTranslation } from 'react-i18next';
import { BackToProfile } from '@/components/BackToProfile';
import { Header } from '@/components/Header';
import { Footer } from '@/components/Footer';
import { CalendarWidget } from '@/components/calendar/CalendarWidget';

const Calendar = () => {
    const { t } = useTranslation();

    return (
        <div className="min-h-screen bg-background flex flex-col">
            <Header />
            <main className="flex-1 container mx-auto py-8 px-4 max-w-7xl animate-in fade-in duration-700">
                <BackToProfile />

                <div className="mb-8 pl-1">
                    <h1 className="text-4xl font-black tracking-tight mb-2 bg-gradient-to-r from-primary to-primary/60 bg-clip-text text-transparent">
                        {t('hr.calendar.title')}
                    </h1>
                    <p className="text-muted-foreground font-medium text-lg italic opacity-80">
                        {t('hr.calendar.subtitle')}
                    </p>
                </div>

                <CalendarWidget />
            </main>
            <Footer />
        </div>
    );
};

export default Calendar;
