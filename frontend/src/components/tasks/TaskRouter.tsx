import React from 'react';
import { Loader2 } from 'lucide-react';
import { useActiveProfile } from '@/hooks/useActiveProfile';
import { usePermissions } from '@/hooks/usePermissions';

import HRTasks from '@/pages/hr/HRTasks';
import EmployeeTasks from '@/pages/hr/EmployeeTasks';

export const TaskRouter: React.FC = () => {
    const { activeProfile, isLoading } = useActiveProfile();
    const permissions = usePermissions();
    // Раньше это был type guard над профилем; теперь права приходят
    // отдельно, поэтому проверка на наличие профиля стала явной.
    const isRegularEmployee = permissions.atLeast('tasks', 'read') && !permissions.atLeast('tasks', 'admin');

    if (isLoading) {
        return (
            <div className="flex justify-center items-center py-12">
                <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
        );
    }

    if (activeProfile && isRegularEmployee) {
        return <EmployeeTasks profile={activeProfile} />;
    }

    return <HRTasks />;
};
