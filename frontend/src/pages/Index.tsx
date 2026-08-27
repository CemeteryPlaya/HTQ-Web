import React from 'react';
import { Header } from '@/components/Header';
import { useLanguageTransition } from '@/hooks/use-language-transition';
import { HeroSection } from '@/components/HeroSection';
import { LazySection } from '@/components/LazySection';
import { Footer } from '@/components/Footer';
import { HomeBlock } from '@/components/HomeBlock';
import { CustomHomeBlocks } from '@/components/CustomHomeBlocks';

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
      <HomeBlock sectionKey="hero">
        <HeroSection />
      </HomeBlock>

      <LazySection height="min-h-[600px]">
        <HomeBlock sectionKey="directions">
          <ActivityDirections />
        </HomeBlock>
      </LazySection>

      <LazySection height="min-h-[400px]">
        <HomeBlock sectionKey="invest">
          <InvestCTA />
        </HomeBlock>
      </LazySection>

      <LazySection height="min-h-[600px]">
        <HomeBlock sectionKey="projects">
          <ProjectsSection />
        </HomeBlock>
      </LazySection>

      <LazySection height="min-h-[600px]">
        <HomeBlock sectionKey="services">
          <ServicesSection />
        </HomeBlock>
      </LazySection>

      <LazySection height="min-h-[300px]">
        <HomeBlock sectionKey="stats">
          <StatsSection />
        </HomeBlock>
      </LazySection>

      <LazySection height="min-h-[600px]">
        <HomeBlock sectionKey="mission">
          <MissionSection />
        </HomeBlock>
      </LazySection>

      <LazySection height="min-h-[600px]">
        <HomeBlock sectionKey="about">
          <AboutSection />
        </HomeBlock>
      </LazySection>

      <LazySection height="min-h-[300px]">
        <HomeBlock sectionKey="partners">
          <PartnersSection />
        </HomeBlock>
      </LazySection>

      <CustomHomeBlocks />

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
