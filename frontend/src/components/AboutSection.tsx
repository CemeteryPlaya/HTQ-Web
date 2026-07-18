import { useTranslation } from 'react-i18next';
import { ArrowRight, Leaf, Sun, Zap } from 'lucide-react';

const panels1 = '/images/panels1.webp';

export const AboutSection = () => {
  const { t } = useTranslation();

  const features = [
    {
      icon: Sun,
      title: t('about.features.solar.title'),
      description: t('about.features.solar.desc'),
    },
    {
      icon: Leaf,
      title: t('about.features.green.title'),
      description: t('about.features.green.desc'),
    },
    {
      icon: Zap,
      title: t('about.features.efficiency.title'),
      description: t('about.features.efficiency.desc'),
    },
  ];

  return (
    <section id="about" className="section-padding bg-accent">
      <div className="container-custom">
        <div className="grid lg:grid-cols-2 gap-12 lg:gap-20 items-center">
          {/* Image */}
          <div className="relative">
            <div className="rounded-2xl overflow-hidden shadow-elevated">
              <img
                src={panels1}
                alt="Solar Panels"
                loading="lazy"
                className="w-full h-[500px] object-cover"
              />
            </div>
            {/* Floating Card */}
            <div className="bg-card p-6 rounded-xl shadow-card max-w-xs absolute -bottom-6 left-4 lg:left-auto lg:-right-6">
              <div className="flex items-center gap-3 mb-3">
                <div className="w-10 h-10 rounded-full bg-secondary/20 flex items-center justify-center">
                  <Leaf className="text-secondary" size={20} />
                </div>
                <span className="font-display font-semibold">{t('about.eco_friendly')}</span>
              </div>
              <p className="text-muted-foreground text-sm">
                {t('about.eco_desc')}
              </p>
            </div>
          </div>

          {/* Content */}
          <div>
            <span className="text-secondary font-semibold text-sm uppercase tracking-wider">{t('about.tag')}</span>
            <h2 className="font-display text-4xl md:text-5xl font-bold text-foreground mt-2 mb-6">
              {t('about.title')}
            </h2>
            <p className="text-muted-foreground text-lg leading-relaxed mb-6">
              {t('about.p1')}
            </p>
            <p className="text-muted-foreground text-lg leading-relaxed mb-8">
              {t('about.p2')}
            </p>

            {/* Features */}
            <div className="space-y-4 mb-8">
              {features.map((feature) => {
                const Icon = feature.icon;
                return (
                  <div key={feature.title} className="flex items-start gap-4 p-4 rounded-xl bg-card hover:shadow-soft transition-all">
                    <div className="w-12 h-12 rounded-lg bg-primary/10 flex items-center justify-center flex-shrink-0">
                      <Icon className="text-primary" size={24} />
                    </div>
                    <div>
                      <h4 className="font-display font-semibold text-foreground">{feature.title}</h4>
                      <p className="text-muted-foreground text-sm">{feature.description}</p>
                    </div>
                  </div>
                );
              })}
            </div>

            <button className="inline-flex items-center gap-2 btn-primary rounded-full group">
              {t('about.learn_more')}
              <ArrowRight size={18} className="transition-transform group-hover:translate-x-1" />
            </button>
          </div>
        </div>
      </div>
    </section>
  );
};
