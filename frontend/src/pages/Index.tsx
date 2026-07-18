import React from 'react';
import { Header } from '@/components/Header';
import { useLanguageTransition } from '@/hooks/use-language-transition';
import { HeroSection } from '@/components/HeroSection';
import { LazySection } from '@/components/LazySection';
import { Footer } from '@/components/Footer';

// Lazy load below-the-fold sections
const ActivityDirections = React.lazy(() => import('@/components/ActivityDirections').then(m => ({ default: m.ActivityDirections })));
const ProjectsSection = React.lazy(() => import('@/components/ProjectsSection').then(m => ({ default: m.ProjectsSection })));
const ServicesSection = React.lazy(() => import('@/components/ServicesSection').then(m => ({ default: m.ServicesSection })));
const InvestCTA = React.lazy(() => import('@/components/InvestCTA').then(m => ({ default: m.InvestCTA })));
const StatsSection = React.lazy(() => import('@/components/StatsSection').then(m => ({ default: m.StatsSection })));
const MissionSection = React.lazy(() => import('@/components/MissionSection').then(m => ({ default: m.MissionSection })));
const AboutSection = React.lazy(() => import('@/components/AboutSection').then(m => ({ default: m.AboutSection })));
const PartnersSection = React.lazy(() => import('@/components/PartnersSection').then(m => ({ default: m.PartnersSection })));
const NewsSection = React.lazy(() => import('@/components/NewsSection').then(m => ({ default: m.NewsSection })));
const ContactSection = React.lazy(() => import('@/components/ContactSection').then(m => ({ default: m.ContactSection })));

const Index = () => {
  const isChanging = useLanguageTransition();

  return (
    <div className={`min-h-screen language-transition ${isChanging ? 'language-changing' : ''}`}>
      <Header />
      <HeroSection />

      <LazySection height="min-h-[600px]">
        <ActivityDirections />
      </LazySection>

      <LazySection height="min-h-[400px]">
        <InvestCTA />
      </LazySection>

      <LazySection height="min-h-[600px]">
        <ProjectsSection />
      </LazySection>

      <LazySection height="min-h-[600px]">
        <ServicesSection />
      </LazySection>

      <LazySection height="min-h-[300px]">
        <StatsSection />
      </LazySection>

      <LazySection height="min-h-[600px]">
        <MissionSection />
      </LazySection>

      <LazySection height="min-h-[600px]">
        <AboutSection />
      </LazySection>

      <LazySection height="min-h-[300px]">
        <PartnersSection />
      </LazySection>

      <LazySection height="min-h-[500px]">
        <NewsSection />
      </LazySection>

      <LazySection height="min-h-[500px]">
        <ContactSection />
      </LazySection>

      <Footer />
    </div>
  );
};

export default Index;
