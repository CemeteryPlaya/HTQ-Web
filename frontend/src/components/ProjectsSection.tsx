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

  const displayedProjects = projects.slice(0, limit);
  const selectedProject = displayedProjects[expandedIndex ?? 0];

  return (
    <section id="projects" className="section-padding bg-accent">
      <div className="container-custom">
        {/* Header */}
        <div className="grid lg:grid-cols-2 gap-8 lg:gap-16 mb-12">
          <div>
            <span className="text-secondary font-semibold text-sm uppercase tracking-wider">{t('projects.tag')}</span>
            <h2 className="font-display text-4xl md:text-5xl font-bold text-foreground mt-2">
              {t('projects.title')}
            </h2>
          </div>
          <div className="flex items-end">
            <p className="text-muted-foreground text-lg leading-relaxed">
              {t('projects.desc')}
            </p>
          </div>
        </div>

        {/* Projects Grid */}
        <div className="grid lg:grid-cols-2 gap-6">
          {/* Selected Project Image */}
          <div className="relative rounded-2xl overflow-hidden shadow-elevated h-[500px] lg:h-auto">
            <OptimizedImage
              src={selectedProject.image}
              alt={t(selectedProject.nameKey)}
              width={800}
              height={500}
              srcSet={`${selectedProject.image.replace('.webp', '-400w.webp')} 400w, ${selectedProject.image} 800w`}
              sizes="(max-width: 1024px) 100vw, 50vw"
              loading="lazy"
              className="w-full h-full object-cover"
            />
            <div className="absolute inset-0 bg-gradient-to-t from-primary/80 via-primary/20 to-transparent" />
            <div className="absolute bottom-0 left-0 right-0 p-8">
              <div className="flex items-center gap-2 mb-2">
                <Zap size={20} className="text-secondary" />
                <span className={`px-3 py-1 rounded-full text-xs font-medium ${
                  selectedProject.status === 'operational'
                    ? 'bg-primary/30 text-primary-foreground'
                    : 'bg-secondary/40 text-secondary-foreground'
                }`}>
                  {t(`projects.status.${selectedProject.status}`)}
                </span>
              </div>
              <h3 className="font-display text-3xl font-bold text-primary-foreground mb-2">
                {t(selectedProject.nameKey)}
              </h3>
              <p className="text-primary-foreground/80">
                {selectedProject.power} • {t(selectedProject.locationKey)}
              </p>
              <p className="text-primary-foreground/70 text-sm mt-3 leading-relaxed max-w-md">
                {t(selectedProject.descriptionKey)}
              </p>
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
                  onClick={() => setExpandedIndex(expandedIndex === index ? null : index)}
                  className="w-full flex items-center justify-between p-5 text-left"
                >
                  <div className="flex items-center gap-4">
                    <div className={`w-10 h-10 rounded-lg flex items-center justify-center transition-colors ${expandedIndex === index ? 'bg-primary' : 'bg-accent'
                      }`}>
                      <Zap size={18} className={expandedIndex === index ? 'text-primary-foreground' : 'text-primary'} />
                    </div>
                    <div>
                      <h4 className="font-display font-semibold text-foreground">{t(project.nameKey)}</h4>
                      <span className="text-sm text-muted-foreground">{project.power}</span>
                    </div>
                  </div>
                  <div className={`w-8 h-8 rounded-full flex items-center justify-center transition-all ${expandedIndex === index
                      ? 'bg-secondary text-secondary-foreground rotate-180'
                      : 'bg-accent text-foreground'
                    }`}>
                    {expandedIndex === index ? <Minus size={16} /> : <Plus size={16} />}
                  </div>
                </button>

                {expandedIndex === index && (
                  <div className="px-5 pb-5 animate-fade-in">
                    <div className="pl-14 flex items-center gap-6 text-sm text-muted-foreground">
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
              className="flex items-center justify-center gap-2 text-primary font-semibold hover:gap-4 transition-all group pt-4"
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
