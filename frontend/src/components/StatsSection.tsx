import { useEffect, useState, useRef } from 'react';
import { useTranslation } from 'react-i18next';

import { companyStats } from '@/data/company';

const useCountUp = (end: number, duration: number = 2000) => {
  const [count, setCount] = useState(0);
  const [hasStarted, setHasStarted] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !hasStarted) {
          setHasStarted(true);
        }
      },
      { threshold: 0.3 }
    );

    if (ref.current) {
      observer.observe(ref.current);
    }

    return () => observer.disconnect();
  }, [hasStarted]);

  useEffect(() => {
    if (!hasStarted) return;

    let startTime: number;
    const step = (timestamp: number) => {
      if (!startTime) startTime = timestamp;
      const progress = Math.min((timestamp - startTime) / duration, 1);
      setCount(Math.floor(progress * end));
      if (progress < 1) {
        requestAnimationFrame(step);
      }
    };
    requestAnimationFrame(step);
  }, [hasStarted, end, duration]);

  return { count, ref };
};

interface StatCardProps {
  value: number;
  suffix: string;
  label: string;
}

/**
 * Отдельный компонент, потому что ``useCountUp`` — хук: вызывать его в теле
 * ``.map`` нельзя (react-hooks/rules-of-hooks), порядок хуков поехал бы, как
 * только число карточек перестанет быть константой.
 */
const StatCard = ({ value, suffix, label }: StatCardProps) => {
  const { count, ref } = useCountUp(value);

  return (
    <div
      ref={ref}
      className="text-center p-8 rounded-2xl bg-primary-foreground/5 backdrop-blur border border-primary-foreground/10"
    >
      <div className="stat-number text-secondary">
        {count}
        <span className="text-4xl">{suffix}</span>
      </div>
      <p className="text-primary-foreground/80 font-medium mt-2">{label}</p>
    </div>
  );
};

export const StatsSection = () => {
  const { t } = useTranslation();

  // Цифры — из единого источника, чтобы не расходиться с Hero и карточкой миссии.
  const stats = [
    { value: companyStats.years, suffix: '+', label: t('stats.items.years') },
    { value: companyStats.projects, suffix: '+', label: t('stats.items.projects') },
    { value: companyStats.totalMw, suffix: '', label: t('stats.items.megawatts') },
  ];

  return (
    <section className="py-20 bg-primary relative overflow-hidden">
      {/* Background Pattern */}
      <div className="absolute inset-0 opacity-10">
        <div className="absolute top-0 left-0 w-96 h-96 bg-secondary rounded-full blur-3xl -translate-x-1/2 -translate-y-1/2" />
        <div className="absolute bottom-0 right-0 w-96 h-96 bg-secondary rounded-full blur-3xl translate-x-1/2 translate-y-1/2" />
      </div>

      <div className="container-custom relative z-10">
        {/* Header */}
        <div className="text-center max-w-3xl mx-auto mb-16">
          <span className="text-secondary font-semibold text-sm uppercase tracking-wider">{t('stats.tag')}</span>
          <h2 className="font-display text-4xl md:text-5xl font-bold text-primary-foreground mt-2">
            {t('stats.title')}
          </h2>
        </div>

        {/* Stats Grid */}
        <div className="grid md:grid-cols-3 gap-8 lg:gap-12">
          {stats.map((stat) => (
            <StatCard key={stat.label} value={stat.value} suffix={stat.suffix} label={stat.label} />
          ))}
        </div>
      </div>
    </section>
  );
};
