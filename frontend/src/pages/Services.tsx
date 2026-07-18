import { useTranslation } from 'react-i18next';
import { ArrowRight, ClipboardCheck, Shield, Wrench, Plug, Settings, LucideIcon } from 'lucide-react';
import { Header } from '@/components/Header';
import { Footer } from '@/components/Footer';
import { services } from '@/data/services';
import { useLanguageTransition } from '@/hooks/use-language-transition';
import { OptimizedImage } from '@/components/OptimizedImage';

const iconMap: Record<string, LucideIcon> = {
  ClipboardCheck,
  Shield,
  Wrench,
  Plug,
  Settings,
};

const Services = () => {
  const { t } = useTranslation();
  const isChanging = useLanguageTransition();

  return (
    <div className={`min-h-screen language-transition ${isChanging ? 'language-changing' : ''}`}>
      <Header />

      {/* Hero Banner */}
      <section className="py-24 bg-background">
        <div className="container-custom text-center">
          <span className="text-secondary font-semibold text-sm uppercase tracking-wider">{t('services.tag')}</span>
          <h1 className="font-display text-4xl md:text-5xl font-bold text-foreground mt-2">
            {t('services_page.title')}
          </h1>
          <p className="text-muted-foreground text-lg mt-4 max-w-2xl mx-auto">
            {t('services_page.subtitle')}
          </p>
        </div>
      </section>

      {/* Services List */}
      <section className="py-16 bg-accent">
        <div className="container-custom">
          <div className="space-y-16">
            {services.map((service, index) => {
              const Icon = iconMap[service.iconName];
              return (
                <div
                  key={service.id}
                  className={`grid lg:grid-cols-2 gap-8 items-center ${index % 2 !== 0 ? 'lg:[&>*:first-child]:order-2' : ''}`}
                >
                  <div className="relative rounded-2xl overflow-hidden shadow-elevated h-[350px]">
                    <OptimizedImage
                      src={service.image}
                      alt={t(service.titleKey)}
                      width={800}
                      height={350}
                      srcSet={`${service.image.replace('.webp', '-400w.webp')} 400w, ${service.image} 800w`}
                      sizes="(max-width: 1024px) 100vw, 50vw"
                      loading="lazy"
                      className="w-full h-full object-cover"
                    />
                    <div className="absolute inset-0 bg-gradient-to-t from-primary/40 to-transparent" />
                  </div>
                  <div>
                    <div className="w-14 h-14 rounded-xl bg-primary flex items-center justify-center mb-4">
                      <Icon size={28} className="text-primary-foreground" />
                    </div>
                    <h2 className="font-display text-2xl md:text-3xl font-bold text-foreground mb-4">
                      {t(service.titleKey)}
                    </h2>
                    <p className="text-muted-foreground text-lg leading-relaxed mb-6">
                      {t(service.descKey)}
                    </p>
                    <button className="inline-flex items-center gap-2 text-primary font-semibold hover:gap-4 transition-all group">
                      {t('services_page.learn_more')}
                      <ArrowRight size={18} className="transition-transform group-hover:translate-x-1" />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      <Footer />
    </div>
  );
};

export default Services;
