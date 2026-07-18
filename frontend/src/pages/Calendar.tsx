import React from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { Header } from '@/components/Header';
import { Footer } from '@/components/Footer';
import { CalendarWidget } from '@/components/calendar/CalendarWidget';

const Calendar = () => {
    const { t } = useTranslation();

    return (
        <div className="min-h-screen bg-background flex flex-col">
            <Header />
            <main className="flex-1 container mx-auto py-8 px-4 max-w-7xl animate-in fade-in duration-700">
                <Link
                    to="/myprofile"
                    className="group mb-8 inline-flex items-center gap-2 rounded-full bg-muted/50 px-4 py-2 text-sm font-medium text-muted-foreground backdrop-blur-sm transition-all hover:bg-primary/10 hover:text-primary"
                >
                    <ArrowLeft className="h-4 w-4 transition-transform group-hover:-translate-x-1" />
                    {t('hr.backToMain', 'Назад в профиль')}
                </Link>

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
