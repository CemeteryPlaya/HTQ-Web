import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { MapPin, Zap } from 'lucide-react';
import { Header } from '@/components/Header';
import { Footer } from '@/components/Footer';
import { projects, Project } from '@/data/projects';
import { useLanguageTransition } from '@/hooks/use-language-transition';
import { ProjectModal } from '@/components/ProjectModal';

const Projects = () => {
  const { t } = useTranslation();
  const isChanging = useLanguageTransition();
  const [selectedProject, setSelectedProject] = useState<Project | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);

  const handleProjectClick = (project: Project) => {
    setSelectedProject(project);
    setIsModalOpen(true);
  };

  const goToNextProject = () => {
    if (!selectedProject) return;
    const currentIndex = projects.findIndex(p => p.id === selectedProject.id);
    const nextIndex = (currentIndex + 1) % projects.length;
    setSelectedProject(projects[nextIndex]);
  };

  const goToPrevProject = () => {
    if (!selectedProject) return;
    const currentIndex = projects.findIndex(p => p.id === selectedProject.id);
    const prevIndex = (currentIndex - 1 + projects.length) % projects.length;
    setSelectedProject(projects[prevIndex]);
  };

  return (
    <div className={`min-h-screen language-transition ${isChanging ? 'language-changing' : ''}`}>
      <Header />

      {/* Hero Banner */}
      <section className="py-24 bg-accent">
        <div className="container-custom text-center">
          <span className="text-secondary font-semibold text-sm uppercase tracking-wider">{t('projects.tag')}</span>
          <h1 className="font-display text-4xl md:text-5xl font-bold text-foreground mt-2">
            {t('projects_page.title')}
          </h1>
          <p className="text-muted-foreground text-lg mt-4 max-w-2xl mx-auto">
            {t('projects_page.subtitle')}
          </p>
        </div>
      </section>

      {/* Projects Grid */}
      <section className="py-16 bg-background">
        <div className="container-custom">
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-8">
            {projects.map((project) => (
              <div
                key={project.id}
                className="group rounded-2xl overflow-hidden shadow-soft card-hover bg-card cursor-pointer"
                onClick={() => handleProjectClick(project)}
              >
                <div className="relative h-48 overflow-hidden">
                  <img
                    src={project.image}
                    alt={t(project.nameKey)}
                    className="w-full h-full object-cover transition-transform duration-500 group-hover:scale-110"
                  />
                  <div className="absolute inset-0 bg-gradient-to-t from-primary/60 to-transparent" />
                  <div className="absolute bottom-0 left-0 right-0 p-4">
                    <h2 className="font-display font-bold text-lg text-primary-foreground">{t(project.nameKey)}</h2>
                  </div>
                </div>
                <div className="p-6">
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
                      <MapPin size={14} />
                      <span>{t(project.locationKey)}</span>
                    </div>
                    <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
                      <Zap size={14} />
                      <span>{project.power}</span>
                    </div>
                  </div>
                  <div className={`inline-block px-3 py-1 rounded-full text-xs font-medium mb-3 ${project.status === 'operational'
                    ? 'bg-primary/10 text-primary'
                    : 'bg-secondary/20 text-secondary-foreground'
                    }`}>
                    {t(`projects.status.${project.status}`)}
                  </div>
                  <p className="text-muted-foreground text-sm leading-relaxed">
                    {t(project.descriptionKey)}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <Footer />

      <ProjectModal
        project={selectedProject}
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        onNext={goToNextProject}
        onPrev={goToPrevProject}
      />
    </div>
  );
};

export default Projects;
