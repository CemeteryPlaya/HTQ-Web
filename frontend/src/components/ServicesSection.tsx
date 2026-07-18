import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { ArrowRight, Shield, Settings, Wrench, Plug, ClipboardCheck, LucideIcon } from 'lucide-react';
import { services } from '@/data/services';

const iconMap: Record<string, LucideIcon> = {
  ClipboardCheck,
  Shield,
  Wrench,
  Plug,
  Settings,
};

export const ServicesSection = () => {
  const { t } = useTranslation();
  const [activeService, setActiveService] = useState(0);

  const displayedServices = services.filter(s => s.featuredOnMain);

  return (
    <section id="services" className="section-padding bg-background">
      <div className="container-custom">
        {/* Header */}
        <div className="text-center max-w-3xl mx-auto mb-16">
          <span className="text-secondary font-semibold text-sm uppercase tracking-wider">{t('services.tag')}</span>
          <h2 className="font-display text-4xl md:text-5xl font-bold text-foreground mt-2 mb-4">
            {t('services.title')}
          </h2>
          <p className="text-muted-foreground text-lg">
            {t('services.desc')}
          </p>
        </div>

        {/* Services Grid */}
        <div className="grid lg:grid-cols-5 gap-4 mb-12">
          {displayedServices.map((service, index) => {
            const Icon = iconMap[service.iconName];
            return (
              <button
                key={service.id}
                onClick={() => setActiveService(index)}
                className={`p-6 rounded-xl text-left transition-all duration-300 ${activeService === index
                    ? 'bg-primary text-primary-foreground shadow-elevated scale-105'
                    : 'bg-card hover:bg-accent text-foreground'
                  }`}
              >
                <Icon size={28} className={activeService === index ? 'text-secondary' : 'text-primary'} />
                <h4 className="font-display font-semibold mt-4 text-sm leading-tight">
                  {t(service.titleKey)}
                </h4>
              </button>
            );
          })}
        </div>

        {/* Active Service Detail */}
        <div className="grid lg:grid-cols-2 gap-8 items-center">
          <div
            key={`image-${activeService}`}
            className="relative rounded-2xl overflow-hidden shadow-elevated h-[400px] transition-all duration-500 animate-fade-in-up"
          >
            <img
              src={displayedServices[activeService].image}
              alt={t(displayedServices[activeService].titleKey)}
              className="w-full h-full object-cover transition-all duration-500"
            />
            <div className="absolute inset-0 bg-gradient-to-t from-primary/40 to-transparent" />
          </div>
          <div
            key={`content-${activeService}`}
            className="lg:pl-8 transition-all duration-500 animate-fade-in-up"
          >
            <div className="inline-flex items-center gap-2 text-secondary font-semibold mb-4">
              {(() => {
                const Icon = iconMap[displayedServices[activeService].iconName];
                return <Icon size={20} className="transition-transform duration-300" />;
              })()}
              <span className="transition-opacity duration-300">
                {t('services.step', { current: activeService + 1, total: displayedServices.length })}
              </span>
            </div>
            <h3 className="font-display text-3xl md:text-4xl font-bold text-foreground mb-4 transition-opacity duration-300">
              {t(displayedServices[activeService].titleKey)}
            </h3>
            <p className="text-muted-foreground text-lg leading-relaxed mb-6 transition-opacity duration-300">
              {t(displayedServices[activeService].descKey)}
            </p>
            <Link
              to="/services"
              className="inline-flex items-center gap-2 text-primary font-semibold hover:gap-4 transition-all group"
            >
              {t('services.view_all')}
              <ArrowRight size={18} className="transition-transform group-hover:translate-x-1" />
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
};
