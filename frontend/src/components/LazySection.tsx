import React, { useState, useEffect, useRef, Suspense } from 'react';

export const LazySection = ({
    children,
    height = 'min-h-[500px]'
}: {
    children: React.ReactNode,
    height?: string
}) => {
    const [isVisible, setIsVisible] = useState(false);
    const ref = useRef<HTMLDivElement>(null);

    useEffect(() => {
        // If it's already visible, we don't need the observer
        if (isVisible) return;

        const observer = new IntersectionObserver(
            (entries) => {
                // When the element enters the viewport (with a 300px margin)
                if (entries[0].isIntersecting) {
                    setIsVisible(true);
                    if (ref.current) observer.unobserve(ref.current);
                }
            },
            // Load the component when it's 300px away from the screen bottom
            { rootMargin: '300px' }
        );

        if (ref.current) {
            observer.observe(ref.current);
        }

        return () => {
            observer.disconnect();
        };
    }, [isVisible]);

    return (
        <div ref={ref} className={!isVisible ? height : ''} suppressHydrationWarning>
            {isVisible ? (
                <Suspense fallback={<div className={`flex items-center justify-center w-full ${height}`}><div className="animate-pulse bg-gray-100 rounded-md w-full h-full"></div></div>}>
                    {children}
                </Suspense>
            ) : null}
        </div>
    );
};
