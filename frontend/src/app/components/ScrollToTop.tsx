import { useEffect } from 'react';
import { useLocation, useNavigationType } from 'react-router-dom';

// On new route (PUSH/REPLACE) — scroll to top.
// On back/forward (POP) — leave browser's restored scroll alone, otherwise
// returning to a long page would forget where the user was.
export const ScrollToTop = () => {
    const { pathname } = useLocation();
    const navigationType = useNavigationType();

    useEffect(() => {
        if (navigationType === 'POP') return;
        window.scrollTo({ top: 0, left: 0, behavior: 'instant' as ScrollBehavior });
    }, [pathname, navigationType]);

    return null;
};
