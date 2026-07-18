import { Task } from './tasks';

export type CalendarEventType = 'common' | 'department' | 'personal' | 'conference';

export type RsvpStatus = 'pending' | 'accepted' | 'declined';

export interface CalendarParticipant {
  user_id: number;
  full_name?: string;
  email?: string;
  avatar_url?: string | null;
  rsvp_status?: RsvpStatus;
}

export interface CalendarEvent {
  id: number;
  title: string;
  description: string;
  event_type: CalendarEventType;
  creator: number;
  creator_id?: number;
  creator_name: string;
  department?: number;
  department_id?: number | null;
  department_name?: string;
  start_at: string;
  end_at: string;
  is_all_day: boolean;
  rrule?: string;
  color?: string | null;
  conference_room_id?: string;
  is_global?: boolean;
  exceptions?: EventException[];
  participants?: CalendarParticipant[];
  /** Used only on create/update — server returns the rich ``participants`` list. */
  participant_user_ids?: number[];
  created_at: string;
  updated_at: string;
}

export interface EventException {
  id: number;
  event: number;
  original_date: string;
  is_cancelled: boolean;
  new_start_at?: string;
  new_end_at?: string;
}

export interface ProductionDay {
  date: string;
  day_type: 'working' | 'weekend' | 'holiday' | 'short';
  working_days_since_epoch: number;
  note?: string;
}

export interface CalendarTimeline {
  tasks: Task[];
  events: CalendarEvent[];
}
