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
  const [touchStart, setTouchStart] = useState<number | null>(null);
  const [touchEnd, setTouchEnd] = useState<number | null>(null);

  const displayedServices = services.filter(s => s.featuredOnMain);
  const minSwipeDistance = 40;

  const nextService = () => {
    setActiveService((prev) => (prev + 1) % displayedServices.length);
  };

  const prevService = () => {
    setActiveService((prev) => (prev - 1 + displayedServices.length) % displayedServices.length);
  };

  const onTouchStart = (e: React.TouchEvent) => {
    setTouchEnd(null);
    setTouchStart(e.targetTouches[0].clientX);
  };

  const onTouchMove = (e: React.TouchEvent) => {
    setTouchEnd(e.targetTouches[0].clientX);
  };

  const onTouchEnd = () => {
    if (!touchStart || !touchEnd) return;
    const distance = touchStart - touchEnd;
    const isLeftSwipe = distance > minSwipeDistance;
    const isRightSwipe = distance < -minSwipeDistance;

    if (isLeftSwipe) {
      nextService();
    } else if (isRightSwipe) {
      prevService();
    }
  };

  return (
    <section id="services" className="section-padding bg-background overflow-hidden">
      <div className="container-custom">
        {/* Header */}
        <div className="text-center max-w-3xl mx-auto mb-12 sm:mb-16">
          <span className="text-secondary font-semibold text-sm uppercase tracking-wider">{t('services.tag')}</span>
          <h2 className="font-display text-4xl md:text-5xl font-bold text-foreground mt-2 mb-4">
            {t('services.title')}
          </h2>
          <p className="text-muted-foreground text-base sm:text-lg">
            {t('services.desc')}
          </p>
        </div>

        {/* Services Tabs / Swipe Track */}
        <div className="flex lg:grid lg:grid-cols-5 gap-3 sm:gap-4 overflow-x-auto snap-x scrollbar-none pb-3 lg:pb-0 mb-8 lg:mb-12">
          {displayedServices.map((service, index) => {
            const Icon = iconMap[service.iconName];
            return (
              <button
                key={service.id}
                onClick={() => setActiveService(index)}
                className={`p-5 sm:p-6 rounded-xl text-left shrink-0 w-[180px] sm:w-[220px] lg:w-auto snap-center transition-all duration-300 active:scale-95 ${
                  activeService === index
                    ? 'bg-primary text-primary-foreground shadow-elevated lg:scale-105 ring-2 ring-secondary'
                    : 'bg-card hover:bg-accent text-foreground'
                }`}
              >
                <Icon size={26} className={activeService === index ? 'text-secondary' : 'text-primary'} />
                <h4 className="font-display font-semibold mt-3 text-xs sm:text-sm leading-tight">
                  {t(service.titleKey)}
                </h4>
              </button>
            );
          })}
        </div>

        {/* Active Service Detail with Touch Swipe Support */}
        <div
          onTouchStart={onTouchStart}
          onTouchMove={onTouchMove}
          onTouchEnd={onTouchEnd}
          className="grid lg:grid-cols-2 gap-8 items-center touch-pan-y"
        >
          <div
            key={`image-${activeService}`}
            className="relative rounded-2xl overflow-hidden shadow-elevated h-[300px] sm:h-[400px] transition-all duration-500 animate-fade-in-up"
          >
            <img
              src={displayedServices[activeService].image}
              alt={t(displayedServices[activeService].titleKey)}
              className="w-full h-full object-cover transition-all duration-500"
            />
            <div className="absolute inset-0 bg-gradient-to-t from-primary/40 to-transparent" />
            <div className="lg:hidden absolute bottom-3 right-3 bg-black/40 text-primary-foreground text-[11px] px-2.5 py-1 rounded-full backdrop-blur-xs">
              Свайпайте ← →
            </div>
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
              <span className="transition-opacity duration-300 text-sm">
                {t('services.step', { current: activeService + 1, total: displayedServices.length })}
              </span>
            </div>
            <h3 className="font-display text-2xl sm:text-3xl md:text-4xl font-bold text-foreground mb-4 transition-opacity duration-300">
              {t(displayedServices[activeService].titleKey)}
            </h3>
            <p className="text-muted-foreground text-base sm:text-lg leading-relaxed mb-6 transition-opacity duration-300">
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
