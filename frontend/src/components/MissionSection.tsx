import { useTranslation } from 'react-i18next';
import { ArrowRight, Target, Shield, Lightbulb } from 'lucide-react';
import { Button } from './ui/button';

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
    <section className="section-padding bg-background">
      <div className="container-custom">
        <div className="grid lg:grid-cols-2 gap-12 lg:gap-20 items-center">
          {/* Image Side */}
          <div className="relative order-2 lg:order-1">
            <div className="rounded-2xl overflow-hidden shadow-elevated">
              <img
                src={panels4}
                alt={t('mission.title')}
                loading="lazy"
                className="w-full h-[500px] object-cover"
              />
            </div>
            {/* Stats Card */}
            <div className="glass p-6 rounded-xl shadow-elevated max-w-xs absolute -bottom-6 right-4 lg:-right-6">
              <div className="text-4xl font-display font-bold text-primary mb-1">90+ {t('hero.stats.full_cycle')}</div>
              <p className="text-muted-foreground text-sm">
                MW {t('mission.stats')}
              </p>
            </div>
          </div>

          {/* Content Side */}
          <div className="order-1 lg:order-2">
            <span className="text-secondary font-semibold text-sm uppercase tracking-wider">{t('mission.tag')}</span>
            <h2 className="font-display text-4xl md:text-5xl font-bold text-foreground mt-2 mb-6">
              {t('mission.title')}
            </h2>
            <p className="text-muted-foreground text-lg leading-relaxed mb-8">
              {t('mission.desc')}
            </p>

            {/* Points */}
            <div className="space-y-4 mb-8">
              {missionPoints.map((point) => {
                const Icon = point.icon;
                return (
                  <div
                    key={point.title}
                    className="flex items-start gap-4 p-4 rounded-xl bg-accent hover:bg-accent/80 transition-colors"
                  >
                    <div className="w-12 h-12 rounded-lg bg-primary flex items-center justify-center flex-shrink-0">
                      <Icon className="text-primary-foreground" size={24} />
                    </div>
                    <div>
                      <h4 className="font-display font-semibold text-foreground">{point.title}</h4>
                      <p className="text-muted-foreground text-sm">{point.description}</p>
                    </div>
                  </div>
                );
              })}
            </div>

            <Button className="btn-primary rounded-full group gap-2">
              {t('mission.learn_more')}
              <ArrowRight size={18} className="transition-transform group-hover:translate-x-1" />
            </Button>
          </div>
        </div>
      </div>
    </section>
  );
};
