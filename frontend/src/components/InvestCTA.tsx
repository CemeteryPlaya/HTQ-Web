import { useTranslation } from 'react-i18next';
import { ArrowRight, Leaf, TrendingUp, Globe } from 'lucide-react';
import { Link } from 'react-router-dom';
import { Button } from './ui/button';

const panels13 = '/images/panels13.webp';

export const InvestCTA = () => {
  const { t } = useTranslation();

  return (
    <section className="relative py-24 md:py-32 overflow-hidden">
      {/* Background */}
      <div className="absolute inset-0">
        <img
          src={panels13}
          alt="Wind turbines"
          loading="lazy"
          className="w-full h-full object-cover"
        />
        <div className="absolute inset-0 bg-gradient-to-r from-primary/95 via-primary/85 to-primary/70" />
      </div>

      {/* Floating Icons */}
      <div className="absolute top-20 right-20 hidden lg:block animate-float">
        <div className="w-16 h-16 rounded-full glass-dark flex items-center justify-center">
          <Leaf className="text-secondary" size={28} />
        </div>
      </div>
      <div className="absolute bottom-20 left-20 hidden lg:block animate-float" style={{ animationDelay: '1s' }}>
        <div className="w-16 h-16 rounded-full glass-dark flex items-center justify-center">
          <Globe className="text-secondary" size={28} />
        </div>
      </div>

      <div className="container-custom relative z-10">
        <div className="max-w-4xl mx-auto text-center">
          {/* Label */}
          <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full glass-dark mb-6">
            <TrendingUp className="text-secondary" size={18} />
            <span className="text-primary-foreground/80 text-sm font-medium">{t('invest.tag')}</span>
          </div>

          {/* Heading */}
          <h2 className="font-display text-4xl md:text-5xl lg:text-6xl font-bold text-primary-foreground mb-6">
            {t('invest.title_start')}{' '}
            <span className="text-secondary">{t('invest.title_accent')}</span>
          </h2>

          {/* Subheading */}
          <p className="text-xl md:text-2xl text-primary-foreground/80 mb-8 max-w-2xl mx-auto leading-relaxed">
            {t('invest.desc')}
          </p>

          {/* CTA Button */}
          <a href="/#contact">
            <Button className="btn-secondary rounded-full text-lg px-10 py-6 gap-3 group">
              {t('invest.cta')}
              <ArrowRight size={20} className="transition-transform group-hover:translate-x-1" />
            </Button>
          </a>
        </div>
      </div>
    </section>
  );
};
