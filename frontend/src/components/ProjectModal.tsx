
import { useRef, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { X, MapPin, Zap, Calendar, User, CheckCircle2, ChevronLeft, ChevronRight } from 'lucide-react';
import { Project } from '@/data/projects';

interface ProjectModalProps {
    project: Project | null;
    isOpen: boolean;
    onClose: () => void;
    onNext?: () => void;
    onPrev?: () => void;
}

export const ProjectModal = ({ project, isOpen, onClose, onNext, onPrev }: ProjectModalProps) => {
    const { t } = useTranslation();
    const modalRef = useRef<HTMLDivElement>(null);

    // Handle keyboard navigation and closing
    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent) => {
            if (!isOpen) return;

            if (e.key === 'Escape') onClose();
            if (e.key === 'ArrowRight' && onNext) onNext();
            if (e.key === 'ArrowLeft' && onPrev) onPrev();
        };

        if (isOpen) {
            document.addEventListener('keydown', handleKeyDown);
            // Prevent scrolling when modal is open
            document.body.style.overflow = 'hidden';
        }

        return () => {
            document.removeEventListener('keydown', handleKeyDown);
            document.body.style.overflow = 'unset';
        };
    }, [isOpen, onClose, onNext, onPrev]);

    // Close on outside click
    const handleBackdropClick = (e: React.MouseEvent) => {
        if (modalRef.current && !modalRef.current.contains(e.target as Node)) {
            onClose();
        }
    };

    if (!isOpen || !project) return null;

    return createPortal(
        <div
            className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-background/80 backdrop-blur-sm animate-in fade-in duration-200"
            onClick={handleBackdropClick}
        >
            {/* Navigation Buttons - Desktop */}
            {onPrev && (
                <button
                    onClick={(e) => { e.stopPropagation(); onPrev(); }}
                    className="fixed left-4 md:left-8 top-1/2 -translate-y-1/2 z-50 p-3 rounded-full bg-background/20 hover:bg-background/40 backdrop-blur-md text-foreground transition-all hover:scale-110 hidden md:flex"
                    aria-label="Previous Project"
                >
                    <ChevronLeft size={32} />
                </button>
            )}

            {onNext && (
                <button
                    onClick={(e) => { e.stopPropagation(); onNext(); }}
                    className="fixed right-4 md:right-8 top-1/2 -translate-y-1/2 z-50 p-3 rounded-full bg-background/20 hover:bg-background/40 backdrop-blur-md text-foreground transition-all hover:scale-110 hidden md:flex"
                    aria-label="Next Project"
                >
                    <ChevronRight size={32} />
                </button>
            )}

            <div
                ref={modalRef}
                className="relative w-full max-w-4xl max-h-[90vh] overflow-y-auto bg-card rounded-3xl shadow-2xl border border-border animate-in zoom-in-95 duration-200"
            >
                {/* Navigation Buttons - Mobile (Overlay on Image) */}
                <div className="absolute top-1/2 -translate-y-1/2 left-0 right-0 flex justify-between px-2 md:hidden z-20 pointer-events-none">
                    {onPrev && (
                        <button
                            onClick={(e) => { e.stopPropagation(); onPrev(); }}
                            className="p-2 rounded-full bg-black/30 backdrop-blur-md text-white pointer-events-auto"
                        >
                            <ChevronLeft size={24} />
                        </button>
                    )}
                    {onNext && (
                        <button
                            onClick={(e) => { e.stopPropagation(); onNext(); }}
                            className="p-2 rounded-full bg-black/30 backdrop-blur-md text-white pointer-events-auto"
                        >
                            <ChevronRight size={24} />
                        </button>
                    )}
                </div>

                {/* Close Button */}
                <button
                    onClick={onClose}
                    className="absolute top-4 right-4 z-20 w-10 h-10 rounded-full bg-black/20 hover:bg-black/40 text-white flex items-center justify-center transition-colors backdrop-blur-sm"
                >
                    <X size={20} />
                </button>

                {/* Hero Image */}
                <div className="relative h-64 md:h-80 w-full animate-in fade-in duration-500" key={project.id}>
                    <img
                        src={project.image}
                        alt={t(project.nameKey)}
                        className="w-full h-full object-cover"
                    />
                    <div className="absolute inset-0 bg-gradient-to-t from-background to-transparent" />

                    <div className="absolute bottom-0 left-0 p-6 md:p-8">
                        <div className={`inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-medium mb-3 backdrop-blur-md ${project.status === 'operational'
                            ? 'bg-primary/20 text-primary border border-primary/20'
                            : 'bg-secondary/20 text-secondary-foreground border border-secondary/20'
                            } `}>
                            <span className={`w-1.5 h-1.5 rounded-full ${project.status === 'operational' ? 'bg-primary' : 'bg-secondary-foreground'} `} />
                            {t(`projects.status.${project.status}`)}
                        </div>
                        <h2 className="font-display text-3xl md:text-4xl font-bold text-foreground">
                            {t(project.nameKey)}
                        </h2>
                    </div>
                </div>

                {/* Content */}
                <div className="p-6 md:p-8 grid md:grid-cols-3 gap-8">
                    {/* Main Info */}
                    <div className="md:col-span-2 space-y-8">
                        <div>
                            <h3 className="text-xl font-display font-bold mb-4 flex items-center gap-2">
                                <Calendar size={20} className="text-secondary" />
                                {t('projects.tag')} {/* Using "Projects" tag or finding a generic "About" */}
                            </h3>
                            <p className="text-muted-foreground leading-relaxed whitespace-pre-wrap">
                                {t(project.descriptionKey)}
                            </p>
                        </div>

                        {/* Our Tasks Section */}
                        <div className="bg-accent/50 p-6 rounded-2xl border border-accent">
                            <h3 className="text-lg font-display font-bold mb-3 flex items-center gap-2 text-foreground">
                                <CheckCircle2 size={18} className="text-primary" />
                                {t('services.title')}
                            </h3>
                            <p className="text-foreground/80 font-medium">
                                {t(project.tasksKey)}
                            </p>
                        </div>
                    </div>

                    {/* Sidebar */}
                    <div className="space-y-6">
                        <div className="p-5 bg-accent/30 rounded-2xl border border-accent space-y-4">
                            <div className="flex items-start gap-4">
                                <MapPin className="text-muted-foreground shrink-0 mt-1" size={18} />
                                <div>
                                    <span className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">
                                        Location
                                    </span>
                                    <span className="font-medium">{t(project.locationKey)}</span>
                                </div>
                            </div>

                            <div className="flex items-start gap-4">
                                <Zap className="text-muted-foreground shrink-0 mt-1" size={18} />
                                <div>
                                    <span className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">
                                        Power Capacity
                                    </span>
                                    <span className="font-medium text-lg text-primary">{project.power}</span>
                                </div>
                            </div>

                            {/* Customer */}
                            <div className="flex items-start gap-4">
                                <User className="text-muted-foreground shrink-0 mt-1" size={18} />
                                <div>
                                    <span className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">
                                        Customer
                                    </span>
                                    <span className="font-medium">{t(project.customerKey)}</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>,
        document.body
    );
};
