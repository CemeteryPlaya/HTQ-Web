import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { format, addMonths, subMonths, startOfMonth, endOfMonth, eachDayOfInterval, isSameMonth, isSameDay, startOfWeek, endOfWeek } from 'date-fns';
import { ru, enUS } from 'date-fns/locale';
import { Calendar as CalendarIcon, ChevronLeft, ChevronRight, Plus, Clock, CalendarDays, ListFilter, Video, Pencil, Trash2, Users, Check as CheckIcon, XCircle } from 'lucide-react';
import { Link } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { ScrollArea } from '@/components/ui/scroll-area';
import { fetchCalendarTimeline, createCalendarEvent, updateCalendarEvent, deleteCalendarEvent, fetchProductionCalendar, updateProductionDay, fetchCalendarUserOptions, rsvpCalendarEvent } from '@/api/calendar';
import { fetchDepartments } from '@/api/hr';
import { CalendarEvent } from '@/types/calendar';
import { cn } from '@/lib/utils';
import { useActiveProfile } from '@/hooks/useActiveProfile';
import { isHrManager } from '@/lib/auth/roles';
import { EventForm } from './EventForm';


interface CalendarWidgetProps {
    compact?: boolean;
    initialView?: 'month' | 'timeline';
}

export const CalendarWidget: React.FC<CalendarWidgetProps> = ({
    compact = false, 
    initialView = 'month' 
}) => {
    const { t, i18n } = useTranslation();
    const queryClient = useQueryClient();
    const [currentDate, setCurrentDate] = useState(new Date());
    const [view, setView] = useState<'month' | 'timeline'>(initialView);
    const [isEventModalOpen, setIsEventModalOpen] = useState(false);
    const [selectedDay, setSelectedDay] = useState<Date | null>(null);
    const [isDayModalOpen, setIsDayModalOpen] = useState(false);
    const [editingEvent, setEditingEvent] = useState<CalendarEvent | null>(null);
    const [isEditModalOpen, setIsEditModalOpen] = useState(false);
    const [now, setNow] = useState(new Date());
    // Pre-filled date when the user clicked a specific day cell to create an
    // event — keeps the create flow one tap away.
    const [prefilledDate, setPrefilledDate] = useState<Date | null>(null);

    useEffect(() => {
        const timer = setInterval(() => setNow(new Date()), 10000);
        return () => clearInterval(timer);
    }, []);

    const { activeProfile } = useActiveProfile({
        staleTime: 5 * 60 * 1000,
    });
    
    // Check if the current user has permission to edit holidays
    const isAuthorized = isHrManager(activeProfile);

    const dateLocale = i18n.language === 'ru' ? ru : enUS;
    const startDate = startOfMonth(currentDate);
    const endDate = endOfMonth(currentDate);

    // Fetch unified timeline (tasks + events)
    const { data: timeline } = useQuery({
        queryKey: ['calendar-timeline', format(startDate, 'yyyy-MM-dd'), format(endDate, 'yyyy-MM-dd')],
        queryFn: () => fetchCalendarTimeline(format(startDate, 'yyyy-MM-dd'), format(endDate, 'yyyy-MM-dd')),
    });

    // Treat malformed/absent responses as empty so the widget does not crash
    // the whole /myprofile page with `forEach` on undefined.
    const safeTasks = Array.isArray(timeline?.tasks) ? timeline!.tasks : [];
    const safeEvents = Array.isArray(timeline?.events) ? timeline!.events : [];

    // Fetch production calendar
    const { data: prodDays } = useQuery({
        queryKey: ['production-calendar', format(startDate, 'yyyy-MM-dd'), format(endDate, 'yyyy-MM-dd')],
        queryFn: () => fetchProductionCalendar(format(startDate, 'yyyy-MM-dd'), format(endDate, 'yyyy-MM-dd')),
    });
    const safeProdDays = Array.isArray(prodDays) ? prodDays : [];
    const hasHolidayData = safeProdDays.some((day) => day.note);
    const hasTimelineData = safeTasks.length > 0 || safeEvents.length > 0 || hasHolidayData;

    // Users for the participant multi-select. Loaded lazily — only when the
    // create/edit dialog is open so we don't pay for it on a read-only
    // /myprofile view.
    const isAnyEventDialogOpen = isEventModalOpen || isEditModalOpen;
    const { data: userOptions = [] } = useQuery({
        queryKey: ['calendar-user-options'],
        queryFn: () => fetchCalendarUserOptions(),
        enabled: isAnyEventDialogOpen,
        staleTime: 5 * 60 * 1000,
    });

    // Departments for "Для отдела" type. Same lazy-load condition.
    const { data: departments = [] } = useQuery({
        queryKey: ['calendar-departments'],
        queryFn: fetchDepartments,
        enabled: isAnyEventDialogOpen,
        staleTime: 5 * 60 * 1000,
    });

    const createEventMutation = useMutation({
        mutationFn: createCalendarEvent,
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['calendar-timeline'] });
            setIsEventModalOpen(false);
            setPrefilledDate(null);
        },
    });

    const rsvpMutation = useMutation({
        mutationFn: ({ id, status }: { id: number; status: 'accepted' | 'declined' | 'pending' }) =>
            rsvpCalendarEvent(id, status),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['calendar-timeline'] });
        },
    });

    const updateDayMutation = useMutation({
        mutationFn: ({ dateStr, day_type }: { dateStr: string, day_type: 'working' | 'holiday' }) => 
            updateProductionDay(dateStr, { day_type }),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['production-calendar'] });
        },
    });

    const updateEventMutation = useMutation({
        mutationFn: ({ id, data }: { id: number; data: Partial<CalendarEvent> }) => updateCalendarEvent(id, data),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['calendar-timeline'] });
            setIsEditModalOpen(false);
            setEditingEvent(null);
        },
    });

    const deleteEventMutation = useMutation({
        mutationFn: deleteCalendarEvent,
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['calendar-timeline'] });
        },
    });

    const handleEditEvent = (ev: CalendarEvent) => {
        setEditingEvent(ev);
        setIsEditModalOpen(true);
    };

    // Author-or-admin rule for edit/delete + RSVP-as-author gating.
    const currentUserId = activeProfile?.id ? Number(activeProfile.id) : null;
    const canEditEvent = (ev: CalendarEvent): boolean => {
        if (currentUserId && (ev.creator_id ?? ev.creator) === currentUserId) return true;
        return isAuthorized;
    };
    const myRsvpStatus = (ev: CalendarEvent): 'pending' | 'accepted' | 'declined' | null => {
        if (!currentUserId) return null;
        const me = (ev.participants ?? []).find((p) => p.user_id === currentUserId);
        return me?.rsvp_status ?? null;
    };

    const handleDeleteEvent = (ev: CalendarEvent) => {
        if (window.confirm(t('calendar.confirmDeleteEvent', { title: ev.title }))) {
            deleteEventMutation.mutate(ev.id);
        }
    };

    const toggleHoliday = (date: Date, currentType: string) => {
        if (!isAuthorized) return;
        const dateStr = format(date, 'yyyy-MM-dd');
        // If it's something else like 'short', we just toggle between working and holiday for simplicity here
        const newType = currentType === 'holiday' ? 'working' : 'holiday';
        updateDayMutation.mutate({ dateStr, day_type: newType });
    };

    const handlePrevMonth = () => setCurrentDate(subMonths(currentDate, 1));
    const handleNextMonth = () => setCurrentDate(addMonths(currentDate, 1));
    const handleToday = () => setCurrentDate(new Date());

    const getItemsForDay = (day: Date) => {
        if (!timeline) return { events: [], tasks: [] };
        const dayStr = format(day, 'yyyy-MM-dd');

        // Guard response shape; the widget is mounted broadly and should not
        // crash if calendar data is temporarily unavailable.
        const tasks = Array.isArray(timeline.tasks) ? timeline.tasks : [];
        const events = Array.isArray(timeline.events) ? timeline.events : [];

        const dayTasks: any[] = [];
        tasks.forEach(task => {
            if (task.start_date === dayStr) {
                dayTasks.push({ ...task, isStart: true, isDeadline: false });
            }
            if (task.due_date === dayStr) {
                dayTasks.push({ ...task, isStart: false, isDeadline: true });
            }
        });

        return {
            events: events.filter(e => format(new Date(e.start_at), 'yyyy-MM-dd') === dayStr),
            tasks: dayTasks
        };
    };

    const getDayType = (day: Date) => {
        const dayStr = format(day, 'yyyy-MM-dd');
        return safeProdDays.find(d => d.date === dayStr)?.day_type || 'working';
    };

    const renderMonthGrid = () => {
        const start = startOfWeek(startOfMonth(currentDate), { weekStartsOn: 1 });
        const end = endOfWeek(endOfMonth(currentDate), { weekStartsOn: 1 });
        const days = eachDayOfInterval({ start, end });

        const weekDays = [
            t('hr.calendar.shortDays.monday'),
            t('hr.calendar.shortDays.tuesday'),
            t('hr.calendar.shortDays.wednesday'),
            t('hr.calendar.shortDays.thursday'),
            t('hr.calendar.shortDays.friday'),
            t('hr.calendar.shortDays.saturday'),
            t('hr.calendar.shortDays.sunday')
        ];

        return (
            <div className="grid grid-cols-7 border-t border-l">
                {weekDays.map(d => (
                    <div key={d} className="bg-muted/50 py-3 text-center text-[10px] md:text-xs font-semibold uppercase tracking-wider text-muted-foreground border-r border-b">
                        {d}
                    </div>
                ))}
                {days.map((day, idx) => {
                    const { events, tasks } = getItemsForDay(day);
                    const dayData = safeProdDays.find(d => d.date === format(day, 'yyyy-MM-dd'));
                    const dayType = dayData?.day_type || 'working';
                    const holidayNote = dayData?.note;
                    const sameMonth = isSameMonth(day, currentDate);
                    const today = isSameDay(day, new Date());

                    return (
                        <div
                            key={idx}
                            className={cn(
                                "min-h-[80px] md:min-h-[120px] p-2 border-r border-b transition-colors relative group",
                                !sameMonth ? "bg-muted/20 text-muted-foreground/50" : "bg-card hover:bg-muted/5",
                                dayType === 'weekend' && "bg-muted/10",
                                dayType === 'holiday' && "bg-red-500/5",
                                isAuthorized && "cursor-pointer"
                            )}
                            onClick={(e) => {
                                // Ignore click if event or task is clicked
                                if ((e.target as HTMLElement).closest('button')) return;
                                setSelectedDay(day);
                                setIsDayModalOpen(true);
                            }}
                            onDoubleClick={(e) => {
                                // Quick "create on this day" shortcut.
                                if ((e.target as HTMLElement).closest('button')) return;
                                setPrefilledDate(day);
                                setIsEventModalOpen(true);
                            }}
                        >
                            <div className="flex justify-between items-start mb-1 md:mb-2">
                                <div className={cn(
                                    "text-[10px] md:text-sm font-medium inline-flex items-center justify-center w-5 h-5 md:w-7 md:h-7 rounded-full",
                                    today && "bg-primary text-primary-foreground",
                                    dayType === 'holiday' && !today && "text-red-500 font-bold"
                                )}>
                                    {format(day, 'd')}
                                </div>
                                {isAuthorized && (
                                    <button
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            toggleHoliday(day, dayType);
                                        }}
                                        className="opacity-0 group-hover:opacity-100 transition-opacity p-1 hover:bg-muted rounded text-muted-foreground hover:text-foreground"
                                        title={dayType === 'holiday' ? t('calendar.makeWorkday') : t('calendar.makeHoliday')}
                                        disabled={updateDayMutation.isPending}
                                    >
                                        <CalendarIcon className="w-3 h-3 md:w-4 md:h-4" />
                                    </button>
                                )}
                            </div>
                            <div className="space-y-0.5 md:space-y-1">
                                {holidayNote && (
                                    <div className="text-[8px] md:text-[10px] px-1 py-0.5 rounded border border-red-500/20 bg-red-500/10 text-red-600 truncate font-semibold" title={holidayNote}>
                                        {holidayNote}
                                    </div>
                                )}
                                {events.map(ev => (
                                    <div key={ev.id} className={cn(
                                        "text-[8px] md:text-[10px] px-1 py-0.5 rounded border border-transparent truncate cursor-pointer",
                                        ev.event_type === 'conference' ? "bg-pink-500/10 text-pink-600 border-pink-500/20 font-semibold" :
                                        ev.event_type === 'common' ? "bg-blue-500/10 text-blue-600 border-blue-500/20" :
                                        ev.event_type === 'department' ? "bg-purple-500/10 text-purple-600 border-purple-500/20" :
                                        "bg-emerald-500/10 text-emerald-600 border-emerald-500/20"
                                    )}>
                                        {ev.event_type === 'conference' && '🎥 '}{ev.title}
                                    </div>
                                ))}
                                {tasks.map((taskItem, idx) => (
                                    <div 
                                        key={`${taskItem.id}-${idx}`} 
                                        className={cn(
                                            "text-[8px] md:text-[10px] px-1 py-0.5 rounded border transition-colors truncate",
                                            taskItem.isDeadline 
                                                ? "bg-red-500/10 text-red-600 border-red-500/20 font-bold" 
                                                : "bg-orange-500/10 text-orange-600 border-orange-500/20"
                                        )}
                                        title={`${taskItem.key}: ${taskItem.summary}`}
                                    >
                                        <span className="mr-1">{taskItem.isDeadline ? '🚨' : '📋'}</span>
                                        <span className="mr-1 opacity-70">
                                            {taskItem.isDeadline ? t('hr.calendar.deadline') : t('hr.calendar.form.start')}:
                                        </span>
                                        <span className="font-semibold">{taskItem.key}:</span> {taskItem.summary}
                                        {taskItem.department_name && (
                                            <span className="ml-1 opacity-70">({taskItem.department_name})</span>
                                        )}
                                    </div>
                                ))}
                            </div>
                        </div>
                    );
                })}
            </div>
        );
    };

    return (
        <div className="flex flex-col gap-6">
            {/* Header Actions */}
            <div className={cn(
                "flex flex-col md:flex-row items-start md:items-center justify-between gap-4 bg-card/50 rounded-3xl border backdrop-blur-sm shadow-xl shadow-foreground/5 transition-all hover:shadow-primary/5",
                compact ? "p-4" : "p-6"
            )}>
                {/* flex-wrap: стрелки + название месяца + «Сегодня» в одну
                    строку на 360px не помещаются и выталкивали кнопку за экран. */}
                <div className="flex flex-wrap items-center gap-2 md:gap-4">
                    <Button variant="outline" size="icon" onClick={handlePrevMonth} aria-label="Previous month" className="rounded-xl md:rounded-2xl shadow-none hover:bg-primary/5 w-8 h-8 md:w-10 md:h-10">
                        <ChevronLeft className="h-4 w-4" />
                    </Button>
                    <div className="flex flex-col items-center">
                        <h2 className={cn(
                            "font-bold text-center capitalize tracking-tight",
                            compact ? "text-lg min-w-[120px]" : "text-xl min-w-[140px] sm:text-2xl sm:min-w-[200px]"
                        )}>
                            {format(currentDate, 'LLLL yyyy', { locale: dateLocale })}
                        </h2>
                        {!compact && (
                            <p className="text-muted-foreground text-xs md:text-sm font-medium opacity-70">
                                {t('hr.calendar.subtitle')}
                            </p>
                        )}
                    </div>
                    <Button variant="outline" size="icon" onClick={handleNextMonth} aria-label="Next month" className="rounded-xl md:rounded-2xl shadow-none hover:bg-primary/5 w-8 h-8 md:w-10 md:h-10">
                        <ChevronRight className="h-4 w-4" />
                    </Button>
                    {!compact && (
                        <Button variant="ghost" onClick={handleToday} className="text-muted-foreground hover:text-primary transition-colors font-semibold">
                            {t('hr.calendar.today')}
                        </Button>
                    )}
                </div>

                <div className="flex items-center gap-3">
                    <Tabs value={view} onValueChange={(v) => setView(v as any)} className="bg-muted/50 p-1 rounded-2xl">
                        <TabsList className="bg-transparent border-none">
                            <TabsTrigger value="month" className="rounded-xl data-[state=active]:bg-card data-[state=active]:shadow-sm px-2 md:px-4">
                                <CalendarDays className="h-4 w-4 mr-0 md:mr-2" /> 
                                <span className="hidden md:inline">{t('hr.calendar.view.grid')}</span>
                            </TabsTrigger>
                            <TabsTrigger value="timeline" className="rounded-xl data-[state=active]:bg-card data-[state=active]:shadow-sm px-2 md:px-4">
                                <ListFilter className="h-4 w-4 mr-0 md:mr-2" />
                                <span className="hidden md:inline">{t('hr.calendar.view.list')}</span>
                            </TabsTrigger>
                        </TabsList>
                    </Tabs>

                    <Dialog
                        open={isEventModalOpen}
                        onOpenChange={(open) => {
                            setIsEventModalOpen(open);
                            if (!open) setPrefilledDate(null);
                        }}
                    >
                        <DialogTrigger asChild>
                            <Button className={cn(
                                "rounded-xl md:rounded-2xl bg-primary hover:bg-primary/90 text-primary-foreground shadow-lg shadow-primary/20 font-bold",
                                compact ? "h-9 px-3" : "h-11 px-6 text-base"
                            )}>
                                <Plus className="h-5 w-5 mr-0 md:mr-2" />
                                <span className="hidden md:inline">{t('hr.common.add')}</span>
                            </Button>
                        </DialogTrigger>
                        <DialogContent className="max-w-xl max-h-[calc(100dvh-2rem)] overflow-y-auto rounded-[2rem] border-none shadow-2xl p-0">
                            <div className="bg-primary p-6 md:p-8 text-primary-foreground relative overflow-hidden">
                                <div className="absolute top-0 right-0 w-32 h-32 bg-white/10 rounded-full -mr-16 -mt-16 blur-3xl" />
                                <DialogHeader>
                                    <DialogTitle className="text-2xl md:text-3xl font-black flex items-center gap-3">
                                        <CalendarIcon className="h-6 w-6 md:h-8 md:w-8" /> {t('hr.calendar.newEvent')}
                                    </DialogTitle>
                                </DialogHeader>
                            </div>
                            <EventForm
                                defaultDate={prefilledDate}
                                userOptions={userOptions}
                                departments={departments}
                                submitting={createEventMutation.isPending}
                                submitLabel={t('hr.common.create')}
                                onCancel={() => { setIsEventModalOpen(false); setPrefilledDate(null); }}
                                onSubmit={(data) => createEventMutation.mutate(data)}
                            />
                        </DialogContent>
                    </Dialog>
                </div>
            </div>

            {/* Main Content Area */}
            <Card className="rounded-[2rem] md:rounded-[2.5rem] shadow-2xl shadow-foreground/5 border-muted/20 overflow-hidden bg-card/80 backdrop-blur-md">
                <CardContent className="p-0">
                    {view === 'month' ? (
                        <div className="animate-in fade-in slide-in-from-bottom-4 duration-700">
                            {renderMonthGrid()}
                        </div>
                    ) : (
                        <ScrollArea className={cn("p-4 md:p-8 animate-in fade-in slide-in-from-bottom-4 duration-700", compact ? "h-[500px]" : "h-[750px]")}>
                            <div className="space-y-4 md:space-y-8">
                                {!hasTimelineData ? (
                                    <div className="text-center py-20 md:py-32 text-muted-foreground flex flex-col items-center gap-4">
                                        <div className="w-12 h-12 md:w-16 md:h-16 rounded-full bg-muted/50 flex items-center justify-center">
                                            <CalendarIcon className="h-6 w-6 md:h-8 md:w-8 opacity-20" />
                                        </div>
                                        <p className="italic text-base md:text-lg">{t('hr.calendar.empty')}</p>
                                    </div>
                                ) : (
                                    <div className="grid gap-4 md:gap-6">
                                        {safeProdDays.filter(d => d.note).sort((a,b) => new Date(a.date).getTime() - new Date(b.date).getTime()).map((d) => (
                                            <div key={`holiday-timeline-${d.date}`} className="flex gap-4 md:gap-6 p-4 md:p-6 rounded-2xl md:rounded-3xl border bg-red-500/5 hover:bg-red-500/10 transition-all relative border-red-500/10 group hover:shadow-xl hover:border-red-500/20">
                                                <div className="w-1 md:w-2 h-full absolute left-0 top-0 bg-red-500" />
                                                <div className="flex-1">
                                                    <div className="flex items-center justify-between mb-2 md:mb-4">
                                                        <h3 className="font-bold md:font-black text-lg md:text-2xl tracking-tight text-red-600/90 flex items-center gap-2">
                                                            <CalendarIcon className="h-5 w-5 md:h-6 md:w-6" /> {d.note}
                                                        </h3>
                                                        <Badge className="bg-red-500 hover:bg-red-600 text-white px-2 md:px-4 py-1 rounded-lg md:rounded-xl font-bold border-none text-[10px] md:text-xs">
                                                            {t('calendar.holiday')}
                                                        </Badge>
                                                    </div>
                                                    <div className="flex flex-col md:flex-row gap-2 md:gap-6 text-xs md:text-sm font-medium text-red-500/80 mt-2">
                                                        <div className="flex items-center gap-1.5 md:gap-2.5 bg-red-500/10 px-3 py-1.5 rounded-full whitespace-nowrap">
                                                            <CalendarDays className="h-3 w-3 md:h-4 md:w-4 text-red-500" /> 
                                                            <span className="font-bold text-red-600">{format(new Date(d.date), 'dd.MM.yyyy')}</span>
                                                        </div>
                                                    </div>
                                                </div>
                                            </div>
                                        ))}
                                        {safeEvents.slice().sort((a,b) => new Date(a.start_at).getTime() - new Date(b.start_at).getTime()).map(ev => (
                                            <div key={ev.id} className={cn("flex gap-4 md:gap-6 p-4 md:p-6 rounded-2xl md:rounded-3xl border bg-card hover:shadow-xl transition-all relative overflow-hidden group hover:border-primary/20 border-muted/20", ev.event_type === 'conference' && "bg-pink-500/5 border-pink-500/10 hover:border-pink-500/20")}>
                                                <div className={cn(
                                                    "w-1 md:w-2 h-full absolute left-0 top-0",
                                                    ev.event_type === 'conference' ? "bg-pink-500" :
                                                    ev.event_type === 'common' ? "bg-blue-500" :
                                                    ev.event_type === 'department' ? "bg-purple-500" :
                                                    "bg-emerald-500"
                                                )} />
                                                <div className="flex-1">
                                                    <div className="flex items-center justify-between mb-2 md:mb-4">
                                                        <h3 className="font-bold md:font-black text-lg md:text-2xl tracking-tight text-foreground/90">
                                                            {ev.event_type === 'conference' && '🎥 '}{ev.title}
                                                        </h3>
                                                        <Badge variant="secondary" className={cn("px-2 md:px-4 py-1 rounded-lg md:rounded-xl capitalize font-bold text-[10px] md:text-xs", ev.event_type === 'conference' && "bg-pink-500 text-white hover:bg-pink-600")}>
                                                            {ev.event_type === 'conference' ? t('hr.calendar.eventTypes.conference') : ev.event_type === 'common' ? t('hr.calendar.eventTypes.common') : ev.event_type === 'department' ? t('hr.calendar.eventTypes.department') : t('hr.calendar.eventTypes.personal')}
                                                        </Badge>
                                                    </div>
                                                    <div className="flex flex-wrap gap-2 md:gap-6 text-xs md:text-sm font-medium text-muted-foreground">
                                                        <div className="flex items-center gap-1.5 md:gap-2.5 bg-muted/40 px-2 md:px-3 py-1 md:py-1.5 rounded-full"><Clock className="h-3 w-3 md:h-4 md:w-4 text-primary" /> {format(new Date(ev.start_at), 'HH:mm')} - {format(new Date(ev.end_at), 'HH:mm')}</div>
                                                        <div className="flex items-center gap-1.5 md:gap-2.5 bg-muted/40 px-2 md:px-3 py-1 md:py-1.5 rounded-full"><CalendarDays className="h-3 w-3 md:h-4 md:w-4 text-primary" /> {format(new Date(ev.start_at), 'dd.MM.yyyy')}</div>
                                                        {ev.event_type === 'conference' && ev.conference_room_id && (() => {
                                                            const start = new Date(ev.start_at);
                                                            const end = new Date(ev.end_at);
                                                            const earlyJoin = new Date(start.getTime() - 5 * 60 * 1000);
                                                            const isActive = now >= earlyJoin && now <= end;
                                                            const isPast = now > end;
                                                            if (isActive) {
                                                                return (
                                                                    <Link
                                                                        to={`/room/${ev.conference_room_id}`}
                                                                        className="inline-flex items-center gap-1.5 bg-pink-500 text-white px-3 py-1.5 rounded-full text-xs font-bold hover:bg-pink-600 transition-colors shadow-sm animate-pulse"
                                                                    >
                                                                        <Video className="h-3.5 w-3.5" />
                                                                        {t('calendar.joinConference')}
                                                                    </Link>
                                                                );
                                                            }
                                                            if (isPast) return null;
                                                            return (
                                                                <span className="inline-flex items-center gap-1.5 bg-muted/60 text-muted-foreground px-3 py-1.5 rounded-full text-xs font-medium">
                                                                    <Clock className="h-3.5 w-3.5" />
                                                                    {t('calendar.startsAt', { time: format(start, 'HH:mm') })}
                                                                </span>
                                                            );
                                                        })()}
                                                    </div>
                                                </div>
                                            </div>
                                        ))}
                                        {safeTasks.map(task => (
                                            <div key={task.id} className="flex gap-4 md:gap-6 p-4 md:p-6 rounded-2xl md:rounded-3xl border bg-orange-500/5 hover:bg-orange-500/10 transition-all relative border-orange-500/10 group hover:shadow-xl">
                                                <div className="w-1 md:w-2 h-full absolute left-0 top-0 bg-orange-500" />
                                                <div className="flex-1">
                                                    <div className="flex items-center justify-between mb-2 md:mb-4">
                                                        <h3 className="font-bold md:font-black text-lg md:text-2xl tracking-tight text-foreground/90">
                                                            📋 {task.key}: {task.summary}
                                                            {task.department_name && (
                                                                <span className="text-muted-foreground text-sm font-normal ml-2 hidden md:inline-block">({task.department_name})</span>
                                                            )}
                                                        </h3>
                                                        <div className="flex gap-2">
                                                            <Badge className="bg-orange-500 text-white px-2 md:px-4 py-1 rounded-lg md:rounded-xl font-bold border-none text-[10px] md:text-xs">{t('hr.calendar.task')}</Badge>
                                                            {task.due_date && <Badge variant="destructive" className="px-2 md:px-4 py-1 rounded-lg md:rounded-xl font-bold text-[10px] md:text-xs">{t('hr.calendar.deadline')}</Badge>}
                                                        </div>
                                                    </div>
                                                    <div className="flex flex-col md:flex-row gap-2 md:gap-6 text-xs md:text-sm font-medium text-muted-foreground mt-2">
                                                        <div className="flex items-center gap-1.5 md:gap-2.5 bg-orange-500/10 px-3 py-1.5 rounded-full whitespace-nowrap">
                                                            <Clock className="h-3 w-3 md:h-4 md:w-4 text-orange-500" /> 
                                                            <span className="opacity-70 mr-1">{t('hr.calendar.form.start')}:</span> {task.start_date || '...'}
                                                        </div>
                                                        <div className="flex items-center gap-1.5 md:gap-2.5 bg-red-500/10 px-3 py-1.5 rounded-full whitespace-nowrap">
                                                            <CalendarDays className="h-3 w-3 md:h-4 md:w-4 text-red-500" /> 
                                                            <span className="opacity-70 mr-1">{t('hr.calendar.deadline')}:</span> {task.due_date}
                                                        </div>
                                                    </div>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>
                        </ScrollArea>
                    )}
                </CardContent>
            </Card>

            {/* Day Details Modal */}
            <Dialog open={isDayModalOpen} onOpenChange={setIsDayModalOpen}>
                <DialogContent className="max-w-md rounded-2xl p-0 overflow-hidden border-none shadow-2xl">
                    {selectedDay && (
                        <>
                            <div className="bg-primary/10 p-6 flex items-center justify-between border-b border-primary/20">
                                <div>
                                    <h3 className="text-xl font-bold text-foreground">
                                        {format(selectedDay, 'd MMMM yyyy', { locale: dateLocale })}
                                    </h3>
                                    <p className="text-muted-foreground text-sm font-medium capitalize mt-1">
                                        {format(selectedDay, 'EEEE', { locale: dateLocale })}
                                    </p>
                                </div>
                            </div>
                            <ScrollArea className="max-h-[60vh] p-6 bg-card">
                                <div className="space-y-4">
                                    {(() => {
                                        const { events, tasks } = getItemsForDay(selectedDay);
                                        const dayType = getDayType(selectedDay);
                                        const holidayNote = safeProdDays.find(d => d.date === format(selectedDay, 'yyyy-MM-dd'))?.note;
                                        const hasItems = events.length > 0 || tasks.length > 0 || holidayNote;

                                        if (!hasItems) {
                                            return (
                                                <div className="text-center py-8 text-muted-foreground">
                                                    <CalendarIcon className="h-10 w-10 mx-auto mb-3 opacity-20" />
                                                    <p>{t('hr.calendar.empty')}</p>
                                                </div>
                                            );
                                        }

                                        return (
                                            <>
                                                {holidayNote && (
                                                    <div className="p-3 rounded-xl border bg-red-500/10 border-red-500/20">
                                                        <h4 className="font-bold text-red-600 flex items-center gap-2">
                                                            <CalendarIcon className="h-4 w-4" /> {holidayNote}
                                                        </h4>
                                                    </div>
                                                )}
                                                
                                                {events.length > 0 && (
                                                    <div className="space-y-2 relative">
                                                        <div className="sticky top-0 bg-card/90 backdrop-blur-sm z-10 py-1 font-semibold text-sm text-foreground/80 my-2">📝 {t('calendar.eventsHeading')}</div>
                                                        {events.sort((a,b) => new Date(a.start_at).getTime() - new Date(b.start_at).getTime()).map(ev => (
                                                            <div key={ev.id} className={cn(
                                                                "p-3 rounded-xl border flex flex-col gap-1.5",
                                                                ev.event_type === 'conference' ? "bg-pink-500/5 hover:bg-pink-500/10 border-pink-500/20" :
                                                                ev.event_type === 'common' ? "bg-blue-500/5 hover:bg-blue-500/10 border-blue-500/20" :
                                                                ev.event_type === 'department' ? "bg-purple-500/5 hover:bg-purple-500/10 border-purple-500/20" :
                                                                "bg-emerald-500/5 hover:bg-emerald-500/10 border-emerald-500/20"
                                                            )}>
                                                                <div className="flex justify-between items-start gap-4">
                                                                    <h5 className="font-bold text-sm tracking-tight">
                                                                        {ev.event_type === 'conference' && '🎥 '}{ev.title}
                                                                    </h5>
                                                                    <Badge variant="outline" className={cn("text-[10px] capitalize whitespace-nowrap", ev.event_type === 'conference' && "bg-pink-500/10 text-pink-600 border-pink-500/30")}>
                                                                        {ev.event_type === 'conference' ? t('hr.calendar.eventTypes.conference') : ev.event_type === 'common' ? t('hr.calendar.eventTypes.common') : ev.event_type === 'department' ? t('hr.calendar.eventTypes.department') : t('hr.calendar.eventTypes.personal')}
                                                                    </Badge>
                                                                </div>
                                                                {ev.description && <p className="text-xs text-muted-foreground line-clamp-2">{ev.description}</p>}
                                                                <div className="text-xs font-semibold text-primary/80 flex items-center gap-1.5 mt-1">
                                                                    <Clock className="w-3.5 h-3.5" />
                                                                    {format(new Date(ev.start_at), 'HH:mm')} - {format(new Date(ev.end_at), 'HH:mm')}
                                                                </div>
                                                                {ev.participants && ev.participants.length > 0 && (
                                                                    <div className="flex flex-col gap-1 mt-1">
                                                                        <div className="text-[11px] text-muted-foreground flex items-center gap-1.5"
                                                                             title={ev.participants.map((p) => `${p.full_name || `#${p.user_id}`}${p.rsvp_status ? ` · ${p.rsvp_status}` : ''}`).join(', ')}>
                                                                            <Users className="w-3 h-3" />
                                                                            {t('calendar.participantsCount', { count: ev.participants.length })}
                                                                            {ev.creator_name && (
                                                                                <span className="opacity-70 ml-1">{t('calendar.byAuthor', { name: ev.creator_name })}</span>
                                                                            )}
                                                                        </div>
                                                                        <div className="flex flex-wrap gap-1">
                                                                            {ev.participants.slice(0, 8).map((p) => (
                                                                                <span
                                                                                    key={p.user_id}
                                                                                    title={`${p.full_name || `#${p.user_id}`}${p.rsvp_status ? ` · ${p.rsvp_status}` : ''}`}
                                                                                    className={cn(
                                                                                        'inline-flex items-center justify-center h-6 w-6 rounded-full text-[10px] font-semibold ring-1',
                                                                                        p.rsvp_status === 'accepted' ? 'bg-emerald-500/15 text-emerald-700 ring-emerald-500/30'
                                                                                            : p.rsvp_status === 'declined' ? 'bg-red-500/10 text-red-600 ring-red-500/20'
                                                                                            : 'bg-muted text-muted-foreground ring-border',
                                                                                    )}
                                                                                >
                                                                                    {(p.full_name || '?').split(' ').filter(Boolean).slice(0, 2).map((w) => w[0]).join('').toUpperCase() || '?'}
                                                                                </span>
                                                                            ))}
                                                                            {ev.participants.length > 8 && (
                                                                                <span className="inline-flex items-center justify-center h-6 px-1.5 rounded-full text-[10px] font-semibold bg-muted text-muted-foreground">
                                                                                    +{ev.participants.length - 8}
                                                                                </span>
                                                                            )}
                                                                        </div>
                                                                    </div>
                                                                )}
                                                                {(() => {
                                                                    const myStatus = myRsvpStatus(ev);
                                                                    if (!myStatus || (currentUserId && (ev.creator_id ?? ev.creator) === currentUserId)) return null;
                                                                    return (
                                                                        <div className="flex gap-1.5 mt-1">
                                                                            <button
                                                                                onClick={(e) => { e.stopPropagation(); rsvpMutation.mutate({ id: ev.id, status: 'accepted' }); }}
                                                                                disabled={rsvpMutation.isPending || myStatus === 'accepted'}
                                                                                className={cn(
                                                                                    'inline-flex items-center gap-1 text-[10px] font-medium px-2 py-1 rounded-md transition-colors',
                                                                                    myStatus === 'accepted'
                                                                                        ? 'bg-emerald-500 text-white'
                                                                                        : 'bg-muted/40 text-muted-foreground hover:bg-emerald-500/10 hover:text-emerald-600',
                                                                                )}
                                                                            >
                                                                                <CheckIcon className="h-3 w-3" /> {t('calendar.rsvpGoing')}
                                                                            </button>
                                                                            <button
                                                                                onClick={(e) => { e.stopPropagation(); rsvpMutation.mutate({ id: ev.id, status: 'declined' }); }}
                                                                                disabled={rsvpMutation.isPending || myStatus === 'declined'}
                                                                                className={cn(
                                                                                    'inline-flex items-center gap-1 text-[10px] font-medium px-2 py-1 rounded-md transition-colors',
                                                                                    myStatus === 'declined'
                                                                                        ? 'bg-red-500 text-white'
                                                                                        : 'bg-muted/40 text-muted-foreground hover:bg-red-500/10 hover:text-red-600',
                                                                                )}
                                                                            >
                                                                                <XCircle className="h-3 w-3" /> {t('calendar.rsvpNotGoing')}
                                                                            </button>
                                                                        </div>
                                                                    );
                                                                })()}
                                                                {ev.event_type === 'conference' && ev.conference_room_id && (() => {
                                                                    const start = new Date(ev.start_at);
                                                                    const end = new Date(ev.end_at);
                                                                    const earlyJoin = new Date(start.getTime() - 5 * 60 * 1000);
                                                                    const isActive = now >= earlyJoin && now <= end;
                                                                    const isPast = now > end;
                                                                    if (isActive) {
                                                                        return (
                                                                            <Link
                                                                                to={`/room/${ev.conference_room_id}`}
                                                                                className="inline-flex items-center gap-1.5 bg-pink-500 text-white px-3 py-1.5 rounded-lg text-xs font-bold hover:bg-pink-600 transition-colors shadow-sm mt-1 w-fit animate-pulse"
                                                                                onClick={(e) => e.stopPropagation()}
                                                                            >
                                                                                <Video className="h-3.5 w-3.5" />
                                                                                {t('calendar.joinConference')}
                                                                            </Link>
                                                                        );
                                                                    }
                                                                    if (isPast) return null;
                                                                    return (
                                                                        <span className="inline-flex items-center gap-1.5 bg-muted/60 text-muted-foreground px-3 py-1.5 rounded-lg text-xs font-medium mt-1 w-fit">
                                                                            <Clock className="h-3.5 w-3.5" />
                                                                            {t('calendar.startsAt', { time: format(start, 'HH:mm') })}
                                                                        </span>
                                                                    );
                                                                })()}
                                                                {canEditEvent(ev) && (
                                                                    <div className="flex gap-1.5 mt-1.5">
                                                                        <button
                                                                            onClick={(e) => { e.stopPropagation(); handleEditEvent(ev); }}
                                                                            className="inline-flex items-center gap-1 text-[10px] font-medium text-muted-foreground hover:text-primary bg-muted/40 hover:bg-muted px-2 py-1 rounded-md transition-colors"
                                                                        >
                                                                            <Pencil className="h-3 w-3" /> {t('common.change')}
                                                                        </button>
                                                                        <button
                                                                            onClick={(e) => { e.stopPropagation(); handleDeleteEvent(ev); }}
                                                                            className="inline-flex items-center gap-1 text-[10px] font-medium text-muted-foreground hover:text-red-500 bg-muted/40 hover:bg-red-500/10 px-2 py-1 rounded-md transition-colors"
                                                                            disabled={deleteEventMutation.isPending}
                                                                        >
                                                                            <Trash2 className="h-3 w-3" /> {t('common.delete')}
                                                                        </button>
                                                                    </div>
                                                                )}
                                                            </div>
                                                        ))}
                                                    </div>
                                                )}

                                                {tasks.length > 0 && (
                                                    <div className="space-y-2 relative">
                                                        <div className="sticky top-0 bg-card/90 backdrop-blur-sm z-10 py-1 font-semibold text-sm text-foreground/80 mt-4 mb-2">📋 {t('hr.calendar.task')}</div>
                                                        {tasks.map((taskItem, idx) => (
                                                            <div key={`${taskItem.id}-${idx}`} className={cn(
                                                                "p-3 rounded-xl border flex flex-col gap-1.5",
                                                                taskItem.isDeadline ? "bg-red-500/5 border-red-500/20 hover:bg-red-500/10" : "bg-orange-500/5 border-orange-500/20 hover:bg-orange-500/10"
                                                            )}>
                                                                <div className="flex justify-between items-start gap-4">
                                                                    <h5 className="font-bold text-sm tracking-tight flex-1">
                                                                        <span className="opacity-60 font-semibold mr-1">{taskItem.key}:</span>
                                                                        {taskItem.summary}
                                                                    </h5>
                                                                    {taskItem.department_name && (
                                                                        <Badge variant="outline" className="text-[10px] bg-background/50 whitespace-nowrap">
                                                                            {taskItem.department_name}
                                                                        </Badge>
                                                                    )}
                                                                </div>
                                                                <div className={cn(
                                                                    "text-xs font-semibold flex items-center gap-1.5 mt-1",
                                                                    taskItem.isDeadline ? "text-red-500/80" : "text-orange-500/80"
                                                                )}>
                                                                    <Clock className="w-3.5 h-3.5" />
                                                                    {taskItem.isDeadline ? `${t('hr.calendar.deadline')}: ${taskItem.due_date}` : `${t('hr.calendar.form.start')}: ${taskItem.start_date || '...'}`}
                                                                </div>
                                                            </div>
                                                        ))}
                                                    </div>
                                                )}
                                            </>
                                        );
                                    })()}
                                </div>
                            </ScrollArea>
                        </>
                    )}
                </DialogContent>
            </Dialog>

            {/* Edit Event Modal */}
            <Dialog open={isEditModalOpen} onOpenChange={(open) => { setIsEditModalOpen(open); if (!open) setEditingEvent(null); }}>
                <DialogContent className="max-w-xl max-h-[calc(100dvh-2rem)] overflow-y-auto rounded-[2rem] border-none shadow-2xl p-0">
                    <div className="bg-primary p-6 md:p-8 text-primary-foreground relative overflow-hidden">
                        <div className="absolute top-0 right-0 w-32 h-32 bg-white/10 rounded-full -mr-16 -mt-16 blur-3xl" />
                        <DialogHeader>
                            <DialogTitle className="text-2xl md:text-3xl font-black flex items-center gap-3">
                                <Pencil className="h-6 w-6 md:h-8 md:w-8" /> {t('calendar.editEvent')}
                            </DialogTitle>
                        </DialogHeader>
                    </div>
                    {editingEvent && (
                        <EventForm
                            initial={editingEvent}
                            excludeFromPicker={editingEvent.creator_id ?? editingEvent.creator ?? null}
                            userOptions={userOptions}
                            departments={departments}
                            submitting={updateEventMutation.isPending}
                            submitLabel={t('common.save')}
                            onCancel={() => { setIsEditModalOpen(false); setEditingEvent(null); }}
                            onSubmit={(data) => updateEventMutation.mutate({ id: editingEvent.id, data })}
                        />
                    )}
                </DialogContent>
            </Dialog>
        </div>
    );
};
