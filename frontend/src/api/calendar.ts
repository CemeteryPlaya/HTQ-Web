import api from '@/api/client';
import { API_ENDPOINTS } from '@/api/endpoints';
import { CalendarEvent, ProductionDay, CalendarTimeline } from '@/types/calendar';

const TASKS = `${API_ENDPOINTS.tasks}/`;
const CALENDAR = `${TASKS}calendar/`;
const TIMELINE = `${CALENDAR}timeline/`;
const PRODUCTION_CALENDAR = `${TASKS}production-calendar/`;

function toTaskCalendarPayload(data: Partial<CalendarEvent>) {
  const eventType = data.event_type;
  const payload: Record<string, unknown> = {
    title: data.title,
    description: data.description ?? '',
    // Full ISO 8601 timestamps with timezone — backend stores them as
    // ``timestamptz``. Keep both ``start_at`` and ``end_at`` so multi-day
    // events round-trip correctly.
    start_at: data.start_at,
    end_at: data.end_at,
    is_all_day: data.is_all_day,
    event_type: eventType,
    conference_room_id: data.conference_room_id ?? null,
    color: data.color ?? null,
    department_id: data.department ?? data.department_id,
    // Drives the M:M participants on the backend. The author is added
    // automatically server-side, so the picker can stay focused on
    // "кого ещё пригласить".
    participant_user_ids: data.participant_user_ids,
  };

  return Object.fromEntries(
    Object.entries(payload).filter(([, value]) => value !== undefined),
  );
}

function normalizeEvent(raw: any): CalendarEvent {
  const startAt = raw.start_at ?? (raw.start_date ? `${raw.start_date}T00:00:00` : raw.created_at);
  const endAt = raw.end_at ?? (raw.end_date ? `${raw.end_date}T23:59:59` : startAt);
  // Trust the backend's event_type now that it's a real column. Fall back
  // to derived value only when serving legacy responses that pre-date
  // migration 007.
  const eventType =
    raw.event_type ?? (raw.is_global ? 'common' : raw.department_id ? 'department' : 'personal');

  return {
    id: raw.id,
    title: raw.title,
    description: raw.description ?? '',
    event_type: eventType,
    creator: raw.creator ?? raw.creator_id ?? 0,
    creator_id: raw.creator_id ?? raw.creator ?? 0,
    creator_name: raw.creator_name ?? '',
    department: raw.department ?? raw.department_id,
    department_id: raw.department_id ?? raw.department ?? null,
    department_name: raw.department_name,
    start_at: startAt,
    end_at: endAt,
    is_all_day: raw.is_all_day ?? true,
    rrule: raw.rrule,
    color: raw.color ?? null,
    conference_room_id: raw.conference_room_id,
    is_global: raw.is_global ?? eventType === 'common',
    exceptions: raw.exceptions ?? [],
    participants: Array.isArray(raw.participants) ? raw.participants : [],
    created_at: raw.created_at,
    updated_at: raw.updated_at,
  };
}

export interface CalendarUserOption {
  id: number;
  full_name: string;
  email: string;
}

export const fetchCalendarUserOptions = async (
  query?: string,
): Promise<CalendarUserOption[]> => {
  const params = new URLSearchParams();
  if (query) params.append('query', query);
  try {
    const res = await api.get<CalendarUserOption[]>(
      `${CALENDAR}users-options/?${params.toString()}`,
    );
    return Array.isArray(res.data) ? res.data : [];
  } catch {
    return [];
  }
};

export const fetchCalendarEvents = async (): Promise<CalendarEvent[]> => {
  try {
    const res = await api.get<any>(CALENDAR);
    const payload = res.data?.results ?? res.data;
    return Array.isArray(payload) ? payload.map(normalizeEvent) : [];
  } catch {
    return [];
  }
};

export const createCalendarEvent = async (data: Partial<CalendarEvent>): Promise<CalendarEvent> => {
  const res = await api.post<CalendarEvent>(CALENDAR, toTaskCalendarPayload(data));
  return normalizeEvent(res.data);
};

export const updateCalendarEvent = async (id: number, data: Partial<CalendarEvent>): Promise<CalendarEvent> => {
  const res = await api.patch<CalendarEvent>(`${CALENDAR}${id}/`, toTaskCalendarPayload(data));
  return normalizeEvent(res.data);
};

export const deleteCalendarEvent = async (id: number): Promise<void> => {
  await api.delete(`${CALENDAR}${id}/`);
};

export const rsvpCalendarEvent = async (
  id: number,
  status: 'pending' | 'accepted' | 'declined',
): Promise<CalendarEvent> => {
  const res = await api.post<CalendarEvent>(`${CALENDAR}${id}/rsvp/`, { status });
  return normalizeEvent(res.data);
};

export const fetchProductionCalendar = async (start?: string, end?: string): Promise<ProductionDay[]> => {
  const params = new URLSearchParams();
  if (start) params.append('date__gte', start);
  if (end) params.append('date__lte', end);
  // Production calendar lives in task-service; keep an empty fallback for older backends.
  try {
    const res = await api.get<any>(`${PRODUCTION_CALENDAR}?${params.toString()}`);
    const payload = res.data?.results ?? res.data;
    return Array.isArray(payload) ? payload : [];
  } catch {
    return [];
  }
};

export const fetchCalendarTimeline = async (start?: string, end?: string): Promise<CalendarTimeline> => {
  const params = new URLSearchParams();
  if (start) params.append('start', start);
  if (end) params.append('end', end);
  // Calendar timeline is global UI data; malformed or unavailable responses
  // should not crash app-wide consumers.
  try {
    const res = await api.get<CalendarTimeline>(`${TIMELINE}?${params.toString()}`);
    const payload = res.data ?? {};
    return {
      tasks: Array.isArray(payload.tasks) ? payload.tasks : [],
      events: Array.isArray(payload.events) ? payload.events.map(normalizeEvent) : [],
    };
  } catch {
    return { tasks: [], events: [] };
  }
};

export const updateProductionDay = async (date: string, data: Partial<ProductionDay>): Promise<ProductionDay> => {
  const res = await api.patch<ProductionDay>(`${PRODUCTION_CALENDAR}${date}/`, data);
  return res.data;
};
