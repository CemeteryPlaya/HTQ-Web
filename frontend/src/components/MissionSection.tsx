import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { ArrowRight, Target, Shield, Lightbulb } from 'lucide-react';
import { Button } from './ui/button';
import { companyStats, formatMw } from '@/data/company';

const panels4 = '/images/panels4.webp';

export const MissionSection = () => {
  const { t } = useTranslation();

  const missionPoints = [
    {
      icon: Target,
      title: t('mission.items.solutions.title'),
      description: t('mission.items.solutions.desc'),
    },
    {
      icon: Shield,
      title: t('mission.items.reliability.title'),
      description: t('mission.items.reliability.desc'),
    },
    {
      icon: Lightbulb,
      title: t('mission.items.innovation.title'),
      description: t('mission.items.innovation.desc'),
    },
  ];

  return (
    <section className="section-padding bg-background overflow-hidden">
      <div className="container-custom">
        <div className="grid lg:grid-cols-2 gap-8 sm:gap-12 lg:gap-20 items-center">
          {/* Image Side */}
          {/* `min-w-0` — см. колонку с каруселью ниже: grid-элемент с min-width
              auto не сжимается уже содержимого и утаскивает сетку за экран. */}
          <div className="relative order-2 lg:order-1 min-w-0">
            <div className="rounded-2xl overflow-hidden shadow-elevated">
              <img
                src={panels4}
                alt={t('mission.title')}
                loading="lazy"
                className="w-full h-[320px] sm:h-[420px] lg:h-[500px] object-cover"
              />
            </div>
            {/* Stats Card */}
            <div className="glass p-4 sm:p-6 rounded-xl shadow-elevated max-w-xs relative sm:absolute mt-4 sm:mt-0 sm:-bottom-6 sm:right-4 lg:-right-6">
              <div className="text-3xl sm:text-4xl font-display font-bold text-primary mb-1">
                {formatMw(companyStats.fullCycleMw, t('common.units.mw'))}
              </div>
              <p className="text-muted-foreground text-xs sm:text-sm">
                {t('mission.stats')}
              </p>
            </div>
          </div>

          {/* Content Side */}
          {/* `min-w-0` обязателен: иначе max-content карусели (3 × 82vw) задаёт
              ширину колонки, заголовок ложится в одну строку и обрезается. */}
          <div className="order-1 lg:order-2 min-w-0">
            <span className="text-secondary font-semibold text-xs sm:text-sm uppercase tracking-wider">{t('mission.tag')}</span>
            <h2 className="font-display text-3xl sm:text-4xl md:text-5xl font-bold text-foreground mt-2 mb-4 sm:mb-6">
              {t('mission.title')}
            </h2>
            <p className="text-muted-foreground text-base sm:text-lg leading-relaxed mb-6 sm:mb-8">
              {t('mission.desc')}
            </p>

            {/* Points */}
            <div className="flex md:block overflow-x-auto snap-x snap-mandatory gap-3 scrollbar-none pb-2 md:pb-0 mb-6 sm:mb-8 space-y-0 md:space-y-4">
              {missionPoints.map((point) => {
                const Icon = point.icon;
                return (
                  <div
                    key={point.title}
                    className="flex items-start gap-3.5 p-4 rounded-xl bg-accent hover:bg-accent/80 transition-colors shrink-0 w-[82vw] sm:w-[320px] md:w-auto snap-center"
                  >
                    <div className="w-10 h-10 sm:w-12 sm:h-12 rounded-lg bg-primary flex items-center justify-center flex-shrink-0">
                      <Icon className="text-primary-foreground" size={20} />
                    </div>
                    <div>
                      <h4 className="font-display font-semibold text-foreground text-base">{point.title}</h4>
                      <p className="text-muted-foreground text-xs sm:text-sm mt-0.5">{point.description}</p>
                    </div>
                  </div>
                );
              })}
            </div>

            <Button asChild className="btn-primary rounded-full group gap-2 min-h-[44px] w-full sm:w-auto">
              <Link to="/services">
                {t('mission.learn_more')}
                <ArrowRight size={18} className="transition-transform group-hover:translate-x-1" />
              </Link>
            </Button>
          </div>
        </div>
      </div>
    </section>
  );
};
