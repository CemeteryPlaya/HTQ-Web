import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useHomeSection } from '@/hooks/useHomeContent';
import { ArrowRight, ChevronLeft, ChevronRight } from 'lucide-react';
import { OptimizedImage } from './OptimizedImage';

const directionLogo1 = '/images/directionsLogo1.webp';
const directionLogo2 = '/images/directionsLogo2.webp';
const directionLogo3 = '/images/directionsLogo3.webp';
const directionLogo4 = '/images/directionsLogo4.webp';
const directionLogo5 = '/images/directionsLogo5.webp';

export const ActivityDirections = () => {
  const { t } = useTranslation();
  const home = useHomeSection('directions');
  const [activeIndex, setActiveIndex] = useState(0);
  const [touchStart, setTouchStart] = useState<number | null>(null);
  const [touchEnd, setTouchEnd] = useState<number | null>(null);

  // Minimum swipe distance (in px)
  const minSwipeDistance = 40;

  const directions = [
    {
      title: t('directions.items.earthworks.title'),
      image: directionLogo1,
      description: t('directions.items.earthworks.desc'),
    },
    {
      title: t('directions.items.construction.title'),
      image: directionLogo2,
      description: t('directions.items.construction.desc'),
    },
    {
      title: t('directions.items.installation.title'),
      image: directionLogo3,
      description: t('directions.items.installation.desc'),
    },
    {
      title: t('directions.items.sunpark.title'),
      image: directionLogo4,
      description: t('directions.items.sunpark.desc'),
    },
    {
      title: t('directions.items.substation.title'),
      image: directionLogo5,
      description: t('directions.items.substation.desc'),
    },
  ];

  const nextSlide = () => {
    setActiveIndex((prev) => (prev + 1) % directions.length);
  };

  const prevSlide = () => {
    setActiveIndex((prev) => (prev - 1 + directions.length) % directions.length);
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
      nextSlide();
    } else if (isRightSwipe) {
      prevSlide();
    }
  };

  return (
    <section className="section-padding bg-card overflow-hidden">
      <div className="container-custom">
        {/* Header */}
        <div className="flex flex-col md:flex-row md:items-end justify-between gap-6 mb-12">
          <div>
            <span className="text-secondary font-semibold text-sm uppercase tracking-wider">{home.text('tag', 'directions.tag')}</span>
            <h2 className="font-display text-4xl md:text-5xl font-bold text-foreground mt-2">
              {home.text('title', 'directions.title')}
            </h2>
          </div>
          <div className="flex gap-3">
            <button
              type="button"
              onClick={prevSlide}
              aria-label="Previous slide"
              className="w-11 h-11 sm:w-12 sm:h-12 rounded-full border-2 border-primary/30 flex items-center justify-center hover:bg-primary hover:text-primary-foreground hover:border-primary active:scale-95 transition-all min-h-[44px] min-w-[44px]"
            >
              <ChevronLeft size={20} />
            </button>
            <button
              type="button"
              onClick={nextSlide}
              aria-label="Next slide"
              className="w-11 h-11 sm:w-12 sm:h-12 rounded-full border-2 border-primary/30 flex items-center justify-center hover:bg-primary hover:text-primary-foreground hover:border-primary active:scale-95 transition-all min-h-[44px] min-w-[44px]"
            >
              <ChevronRight size={20} />
            </button>
          </div>
        </div>

        {/* Swipeable Cards Track on Mobile / Grid on Desktop */}
        <div
          onTouchStart={onTouchStart}
          onTouchMove={onTouchMove}
          onTouchEnd={onTouchEnd}
          className="flex md:grid md:grid-cols-2 lg:grid-cols-3 gap-4 md:gap-6 overflow-x-auto snap-x snap-mandatory scrollbar-none pb-4 md:pb-0"
        >
          {directions.map((direction, index) => (
            <div
              key={direction.title}
              className={`group relative rounded-2xl overflow-hidden card-hover cursor-pointer shrink-0 w-[85vw] sm:w-[360px] md:w-auto snap-center transition-all duration-300 ${
                index === activeIndex ? 'ring-2 ring-secondary' : ''
              }`}
              onClick={() => setActiveIndex(index)}
            >
              <div className="aspect-[4/3] relative">
                <OptimizedImage
                  src={direction.image}
                  alt={direction.title}
                  width={536}
                  height={402}
                  srcSet={`${direction.image.replace('.webp', '-320w.webp')} 320w, ${direction.image} 536w`}
                  sizes="(max-width: 768px) 100vw, (max-width: 1024px) 50vw, 33vw"
                  loading="lazy"
                  className="w-full h-full object-cover transition-transform duration-500 group-hover:scale-110"
                />
                <div className="absolute inset-0 bg-gradient-to-t from-primary/90 via-primary/40 to-transparent" />
              </div>
              <div className="absolute bottom-0 left-0 right-0 p-5 sm:p-6">
                <h3 className="font-display text-lg sm:text-xl font-bold text-primary-foreground mb-1.5 sm:mb-2 transition-transform duration-300 group-hover:-translate-y-2">
                  {direction.title}
                </h3>
                <div className="grid grid-rows-[0fr] group-hover:grid-rows-[1fr] transition-all duration-300 md:grid-rows-[0fr]">
                  <div className="min-h-0 overflow-hidden">
                    <p className="text-primary-foreground/70 text-xs sm:text-sm line-clamp-2">
                      {direction.description}
                    </p>
                    <div className="flex items-center gap-2 text-secondary mt-2">
                      <span className="text-xs sm:text-sm font-medium">{t('directions.more')}</span>
                      <ArrowRight size={16} className="transition-transform group-hover:translate-x-1" />
                    </div>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Mobile Pagination Indicators */}
        <div className="flex md:hidden justify-center items-center gap-2 mt-4 py-1">
          {directions.map((_, idx) => (
            <button
              key={idx}
              type="button"
              onClick={() => setActiveIndex(idx)}
              className="p-1.5 min-h-[36px] flex items-center justify-center"
              aria-label={`Go to slide ${idx + 1}`}
            >
              <span
                className={`h-2 rounded-full transition-all ${
                  idx === activeIndex ? 'w-6 bg-secondary' : 'w-2 bg-muted-foreground/30'
                }`}
              />
            </button>
          ))}
        </div>
      </div>
    </section>
  );
};
