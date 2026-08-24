import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Plus, Minus, MapPin, Zap, ArrowRight } from 'lucide-react';
import { projects } from '@/data/projects';
import { OptimizedImage } from './OptimizedImage';

interface ProjectsSectionProps {
  limit?: number;
}

export const ProjectsSection = ({ limit = 10 }: ProjectsSectionProps) => {
  const { t } = useTranslation();
  const [expandedIndex, setExpandedIndex] = useState<number | null>(0);
  const [touchStart, setTouchStart] = useState<number | null>(null);
  const [touchEnd, setTouchEnd] = useState<number | null>(null);

  const displayedProjects = projects.slice(0, limit);
  const selectedIndex = expandedIndex ?? 0;
  const selectedProject = displayedProjects[selectedIndex];

  const minSwipeDistance = 40;

  const nextProject = () => {
    setExpandedIndex((prev) => ((prev ?? 0) + 1) % displayedProjects.length);
  };

  const prevProject = () => {
    setExpandedIndex((prev) => ((prev ?? 0) - 1 + displayedProjects.length) % displayedProjects.length);
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
      nextProject();
    } else if (isRightSwipe) {
      prevProject();
    }
  };

  return (
    <section id="projects" className="section-padding bg-accent overflow-hidden">
      <div className="container-custom">
        {/* Header */}
        <div className="grid lg:grid-cols-2 gap-8 lg:gap-16 mb-12">
          <div>
            <span className="text-secondary font-semibold text-xs sm:text-sm uppercase tracking-wider">{t('projects.tag')}</span>
            <h2 className="font-display text-3xl sm:text-4xl md:text-5xl font-bold text-foreground mt-2">
              {t('projects.title')}
            </h2>
          </div>
          <div className="flex items-end">
            <p className="text-muted-foreground text-base sm:text-lg leading-relaxed">
              {t('projects.desc')}
            </p>
          </div>
        </div>

        {/* Projects Grid */}
        <div className="grid lg:grid-cols-2 gap-6 items-start">
          {/* Selected Project Card with Swipe Support */}
          <div
            onTouchStart={onTouchStart}
            onTouchMove={onTouchMove}
            onTouchEnd={onTouchEnd}
            className="relative rounded-2xl overflow-hidden shadow-elevated h-[440px] sm:h-[500px] lg:h-[540px] touch-pan-y"
          >
            <OptimizedImage
              src={selectedProject.image}
              alt={t(selectedProject.nameKey)}
              width={800}
              height={500}
              srcSet={`${selectedProject.image.replace('.webp', '-400w.webp')} 400w, ${selectedProject.image} 800w`}
              sizes="(max-width: 1024px) 100vw, 50vw"
              loading="lazy"
              className="w-full h-full object-cover transition-transform duration-700"
            />
            <div className="absolute inset-0 bg-gradient-to-t from-primary/95 via-primary/40 to-transparent" />
            <div className="absolute bottom-0 left-0 right-0 p-6 sm:p-8">
              <div className="flex items-center justify-between gap-2 mb-2">
                <div className="flex items-center gap-2">
                  <Zap size={20} className="text-secondary" />
                  <span className={`px-3 py-1 rounded-full text-xs font-medium ${
                    selectedProject.status === 'operational'
                      ? 'bg-primary/30 text-primary-foreground'
                      : 'bg-secondary/40 text-secondary-foreground'
                  }`}>
                    {t(`projects.status.${selectedProject.status}`)}
                  </span>
                </div>
                {/* Swipe Hint on Mobile */}
                <span className="lg:hidden text-[11px] text-primary-foreground/70 bg-black/30 px-2.5 py-1 rounded-full">
                  {t('common.swipeHint')}
                </span>
              </div>
              <h3 className="font-display text-2xl sm:text-3xl font-bold text-primary-foreground mb-1 sm:mb-2">
                {t(selectedProject.nameKey)}
              </h3>
              <p className="text-primary-foreground/80 text-sm sm:text-base">
                {selectedProject.power} • {t(selectedProject.locationKey)}
              </p>
              <p className="text-primary-foreground/70 text-xs sm:text-sm mt-2 sm:mt-3 leading-relaxed max-w-md line-clamp-3 sm:line-clamp-none">
                {t(selectedProject.descriptionKey)}
              </p>

              {/* Mobile Carousel Indicators */}
              <div className="flex lg:hidden justify-center items-center gap-2 mt-4 py-1">
                {displayedProjects.map((_, idx) => (
                  <button
                    key={idx}
                    onClick={() => setExpandedIndex(idx)}
                    className="p-1 min-h-[32px] flex items-center justify-center"
                    aria-label={`Project ${idx + 1}`}
                  >
                    <span
                      className={`h-2 rounded-full transition-all ${
                        idx === selectedIndex ? 'w-6 bg-secondary' : 'w-2 bg-primary-foreground/40'
                      }`}
                    />
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Projects Accordion */}
          <div className="space-y-3">
            {displayedProjects.map((project, index) => (
              <div
                key={project.id}
                className={`rounded-xl overflow-hidden transition-all duration-300 ${expandedIndex === index
                    ? 'bg-card shadow-card'
                    : 'bg-card/50 hover:bg-card'
                  }`}
              >
                <button
                  type="button"
                  onClick={() => setExpandedIndex(expandedIndex === index ? null : index)}
                  className="w-full flex items-center justify-between p-4 sm:p-5 min-h-[48px] text-left"
                >
                  <div className="flex items-center gap-3 sm:gap-4">
                    <div className={`w-10 h-10 rounded-lg flex items-center justify-center shrink-0 transition-colors ${expandedIndex === index ? 'bg-primary' : 'bg-accent'
                      }`}>
                      <Zap size={18} className={expandedIndex === index ? 'text-primary-foreground' : 'text-primary'} />
                    </div>
                    <div>
                      <h4 className="font-display font-semibold text-foreground text-base sm:text-lg leading-tight">{t(project.nameKey)}</h4>
                      <span className="text-xs sm:text-sm text-muted-foreground">{project.power}</span>
                    </div>
                  </div>
                  <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 transition-all ${expandedIndex === index
                      ? 'bg-secondary text-secondary-foreground rotate-180'
                      : 'bg-accent text-foreground'
                    }`}>
                    {expandedIndex === index ? <Minus size={16} /> : <Plus size={16} />}
                  </div>
                </button>

                {expandedIndex === index && (
                  <div className="px-4 sm:px-5 pb-5 animate-fade-in">
                    <div className="pl-0 sm:pl-14 flex flex-wrap items-center gap-3 sm:gap-6 text-sm text-muted-foreground">
                      <div className="flex items-center gap-1.5">
                        <MapPin size={14} />
                        <span>{t(project.locationKey)}</span>
                      </div>
                      <div className={`px-3 py-1 rounded-full text-xs font-medium ${project.status === 'operational'
                          ? 'bg-primary/10 text-primary'
                          : 'bg-secondary/20 text-secondary-foreground'
                        }`}>
                        {t(`projects.status.${project.status}`)}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            ))}

            <Link
              to="/projects"
              className="flex items-center justify-center gap-2 text-primary font-semibold hover:gap-4 transition-all group min-h-[44px] py-2.5 rounded-xl hover:bg-accent/40"
            >
              {t('projects.view_all')}
              <ArrowRight size={18} className="transition-transform group-hover:translate-x-1" />
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
};
