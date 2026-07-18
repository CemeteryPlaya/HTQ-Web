import React from 'react';
import { Loader2 } from 'lucide-react';
import { useActiveProfile } from '@/hooks/useActiveProfile';
import { usesEmployeeTaskExperience } from '@/lib/auth/roles';

import HRTaskDetail from '@/pages/hr/HRTaskDetail';
import EmployeeTaskDetail from '@/pages/hr/EmployeeTaskDetail';

export const TaskDetailRouter: React.FC = () => {
    const { activeProfile, isLoading } = useActiveProfile();

    if (isLoading) {
        return (
            <div className="flex justify-center items-center py-12">
                <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
        );
    }

    if (usesEmployeeTaskExperience(activeProfile)) {
        return <EmployeeTaskDetail profile={activeProfile} />;
    }

    return <HRTaskDetail />;
};
