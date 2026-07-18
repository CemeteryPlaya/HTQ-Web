import { ChevronDown, Zap, RefreshCw, FileCheck } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { OptimizedImage } from './OptimizedImage';

export const HeroSection = () => {
  const { t } = useTranslation();

  const heroStats = [
    {
      icon: Zap,
      value: t('hero.stats.power_value'),
      description: t('hero.stats.power_desc'),
    },
    {
      icon: RefreshCw,
      value: t('hero.stats.full_cycle'),
      description: t('hero.stats.cycle_desc'),
    },
    {
      icon: FileCheck,
      value: t('hero.stats.own_method'),
      description: t('hero.stats.method_desc'),
    },
  ];

  return (
    <section className="relative min-h-screen flex items-center overflow-hidden">
      {/* Background Image */}
      <div className="absolute inset-0">
        <OptimizedImage
          src="/images/hero-solar-1024w.webp"
          alt="Solar panels field"
          width={1024}
          height={581}
          srcSet="/images/hero-solar-640w.webp 640w, /images/hero-solar-1024w.webp 1024w"
          preferAvif={false}
          sizes="100vw"
          fetchPriority="high"
          loading="eager"
          decoding="sync"
          className="w-full h-full object-cover"
        />
        <div className="absolute inset-0 bg-gradient-to-r from-primary/90 via-primary/70 to-transparent" />
        <div className="absolute inset-0 bg-gradient-to-t from-primary/60 via-transparent to-primary/30" />
      </div>

      {/* Content */}
      <div className="relative z-10 container-custom pt-20 pb-24 md:pb-32">
        <div className="max-w-4xl">
          {/* Tag */}
          <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full glass-dark mb-6 animate-fade-in">
            <span className="w-2 h-2 rounded-full bg-secondary animate-pulse" />
            <span className="text-primary-foreground/80 text-sm font-medium">{t('hero.tag')}</span>
          </div>

          {/* Heading */}
          <h1 className="font-display text-5xl md:text-6xl lg:text-7xl font-bold text-primary-foreground mb-6 animate-fade-in" style={{ animationDelay: '0.1s' }}>
            {t('hero.title_start')}{' '}
            <span className="block text-secondary">{t('hero.title_end')}</span>
          </h1>

          {/* Description */}
          <p className="text-lg md:text-xl text-primary-foreground/80 max-w-2xl mb-8 leading-relaxed animate-fade-in" style={{ animationDelay: '0.2s' }}>
            {t('hero.description')}
          </p>

          {/* Buttons */}
          <div className="flex flex-wrap gap-4 animate-fade-in" style={{ animationDelay: '0.3s' }}>
            <a href="/#contact">
              <span className="btn-primary inline-flex h-14 items-center justify-center rounded-full px-8 py-6 text-lg shadow-soft hover:shadow-lg">
                {t('hero.contact_us')}
              </span>
            </a>
            <Link to="/projects">
              <span className="btn-primary inline-flex h-14 items-center justify-center rounded-full px-8 py-6 text-lg shadow-soft hover:shadow-lg">
                {t('hero.our_projects')}
              </span>
            </Link>
          </div>
        </div>

        {/* Hero Stats - from hi-teck.kz */}
        <div className="mt-10 md:mt-12 grid md:grid-cols-3 gap-6 animate-fade-in" style={{ animationDelay: '0.4s' }}>
          {heroStats.map((stat, index) => {
            const Icon = stat.icon;
            return (
              <div
                key={index}
                className="glass-dark rounded-2xl p-6 flex flex-col items-center text-center hover:bg-white/10 transition-colors"
              >
                <div className="w-14 h-14 rounded-full border-2 border-secondary/50 flex items-center justify-center mb-4">
                  <Icon className="text-secondary" size={28} />
                </div>
                <h3 className="font-display text-xl font-bold text-primary-foreground mb-2">
                  {stat.value}
                </h3>
                <p className="text-primary-foreground/70 text-sm leading-relaxed">
                  {stat.description}
                </p>
              </div>
            );
          })}
        </div>
      </div>

      {/* Scroll Indicator */}
      <a
        href="#projects"
        className="absolute bottom-8 left-1/2 -translate-x-1/2 z-20 flex flex-col items-center gap-2 text-primary-foreground/60 hover:text-primary-foreground transition-colors"
      >
        <span className="text-sm font-medium">{t('hero.learn_more')}</span>
        <ChevronDown className="animate-scroll-bounce" size={24} />
      </a>
    </section>
  );
};
