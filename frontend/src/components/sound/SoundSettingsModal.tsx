import React, { useState, useEffect } from 'react';
import {
  Volume2,
  VolumeX,
  Play,
  Sparkles,
  MessageSquare,
  Video,
  Calendar,
  Clock,
  AlertTriangle,
  Sliders,
} from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogTrigger,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Slider } from '@/components/ui/slider';
import { Switch } from '@/components/ui/switch';
import { Label } from '@/components/ui/label';
import {
  getSoundSettings,
  updateSoundSettings,
  subscribeSoundSettings,
  playMessengerChime,
  playMessengerPop,
  playMeetingReminder,
  playEventCreated,
  playDeadlineWarning,
  playDeadlineUrgent,
  playGlassChime,
  type SoundSettings,
} from '@/lib/sound/soundService';

interface SoundItem {
  id: string;
  name: string;
  category: 'messenger' | 'calendar' | 'deadlines' | 'system';
  description: string;
  icon: React.ElementType;
  color: string;
  play: () => void;
}

const SOUND_PRESETS: SoundItem[] = [
  {
    id: 'msg_chime',
    name: 'Тёплая калимба',
    category: 'messenger',
    description: 'Входящее сообщение (восходящий интервал E5 → A5)',
    icon: MessageSquare,
    color: 'text-cyan-500 bg-cyan-500/10 border-cyan-500/20',
    play: () => playMessengerChime({ bypassThrottle: true }),
  },
  {
    id: 'msg_pop',
    name: 'Капля росы (Bubble Pop)',
    category: 'messenger',
    description: 'Мягкий органичный бульк для активного диалога',
    icon: MessageSquare,
    color: 'text-blue-500 bg-blue-500/10 border-blue-500/20',
    play: () => playMessengerPop({ bypassThrottle: true }),
  },
  {
    id: 'meeting_bell',
    name: 'Executive Chime (Ding-Dong)',
    category: 'calendar',
    description: 'Напоминание о созвоне/конференции (за 5 минут)',
    icon: Video,
    color: 'text-indigo-500 bg-indigo-500/10 border-indigo-500/20',
    play: () => playMeetingReminder({ bypassThrottle: true }),
  },
  {
    id: 'event_created',
    name: 'Schedule Snap',
    category: 'calendar',
    description: 'Событие добавлено в календарь (мажорный аккорд)',
    icon: Calendar,
    color: 'text-emerald-500 bg-emerald-500/10 border-emerald-500/20',
    play: () => playEventCreated({ bypassThrottle: true }),
  },
  {
    id: 'deadline_warning',
    name: 'Focus Pulse',
    category: 'deadlines',
    description: 'Близость дедлайна (двойной спокойный пульс)',
    icon: Clock,
    color: 'text-amber-500 bg-amber-500/10 border-amber-500/20',
    play: () => playDeadlineWarning({ bypassThrottle: true }),
  },
  {
    id: 'deadline_urgent',
    name: 'Urgent Focus',
    category: 'deadlines',
    description: 'Критический срок задачи (< 15 минут)',
    icon: AlertTriangle,
    color: 'text-rose-500 bg-rose-500/10 border-rose-500/20',
    play: () => playDeadlineUrgent({ bypassThrottle: true }),
  },
  {
    id: 'glass_sparkle',
    name: 'Ambient Glass',
    category: 'system',
    description: 'Хрустальный системный перелив',
    icon: Sparkles,
    color: 'text-purple-500 bg-purple-500/10 border-purple-500/20',
    play: () => playGlassChime({ bypassThrottle: true }),
  },
];

export const SoundSettingsModal: React.FC<{ trigger?: React.ReactNode }> = ({ trigger }) => {
  const [settings, setSettings] = useState<SoundSettings>(getSoundSettings);
  const [activeSoundId, setActiveSoundId] = useState<string | null>(null);

  useEffect(() => {
    return subscribeSoundSettings(setSettings);
  }, []);

  const handleToggle = (enabled: boolean) => {
    updateSoundSettings({ enabled });
  };

  const handleVolumeChange = (values: number[]) => {
    const volume = values[0] / 100;
    updateSoundSettings({ volume });
  };

  const handlePlaySound = (sound: SoundItem) => {
    setActiveSoundId(sound.id);
    sound.play();
    setTimeout(() => {
      setActiveSoundId((prev) => (prev === sound.id ? null : prev));
    }, 450);
  };

  return (
    <Dialog>
      <DialogTrigger asChild>
        {trigger || (
          <Button variant="ghost" size="sm" className="gap-2 text-xs h-8">
            <Volume2 className="h-4 w-4" />
            <span>Звуки уведомлений</span>
          </Button>
        )}
      </DialogTrigger>

      <DialogContent className="max-w-xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <div className="flex items-center gap-2">
            <div className="p-2 rounded-xl bg-primary/10 text-primary">
              <Sliders className="h-5 w-5" />
            </div>
            <div>
              <DialogTitle className="text-lg">Звуки уведомлений</DialogTitle>
              <DialogDescription className="text-xs text-muted-foreground mt-0.5">
                Настройка и предпрослушивание синтезированных звуков мессенджера, календаря и задач
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        {/* Global Controls */}
        <div className="flex flex-col gap-4 p-4 rounded-xl border bg-card/60 backdrop-blur-sm shadow-sm">
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label className="text-sm font-semibold flex items-center gap-2">
                {settings.enabled ? (
                  <Volume2 className="h-4 w-4 text-emerald-500" />
                ) : (
                  <VolumeX className="h-4 w-4 text-muted-foreground" />
                )}
                <span>Звуковые сигналы</span>
              </Label>
              <p className="text-xs text-muted-foreground">
                Воспроизведение аудио при входящих сообщениях и событиях
              </p>
            </div>
            <Switch checked={settings.enabled} onCheckedChange={handleToggle} />
          </div>

          <div className="space-y-2 pt-2 border-t">
            <div className="flex justify-between text-xs text-muted-foreground font-medium">
              <span>Громкость</span>
              <span>{Math.round(settings.volume * 100)}%</span>
            </div>
            <Slider
              value={[Math.round(settings.volume * 100)]}
              min={0}
              max={100}
              step={1}
              disabled={!settings.enabled}
              onValueChange={handleVolumeChange}
              className="w-full"
            />
          </div>
        </div>

        {/* Sound Presets List */}
        <div className="space-y-2 pt-2">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground px-1">
            Коллекция звуков (Предпрослушивание)
          </h4>

          <div className="grid grid-cols-1 gap-2">
            {SOUND_PRESETS.map((item) => {
              const Icon = item.icon;
              const isPlaying = activeSoundId === item.id;

              return (
                <div
                  key={item.id}
                  className={`flex items-center justify-between p-3 rounded-xl border transition-all duration-200 ${
                    isPlaying
                      ? 'border-primary/50 bg-primary/5 shadow-sm scale-[1.01]'
                      : 'border-border/60 hover:border-border hover:bg-muted/40'
                  }`}
                >
                  <div className="flex items-center gap-3 min-w-0 pr-2">
                    <div
                      className={`p-2 rounded-lg border shrink-0 transition-transform ${item.color} ${
                        isPlaying ? 'scale-110' : ''
                      }`}
                    >
                      <Icon className="h-4 w-4" />
                    </div>
                    <div className="min-w-0">
                      <div className="text-sm font-medium leading-none truncate">{item.name}</div>
                      <div className="text-xs text-muted-foreground truncate mt-1">
                        {item.description}
                      </div>
                    </div>
                  </div>

                  <Button
                    size="sm"
                    variant={isPlaying ? 'default' : 'outline'}
                    className={`h-8 px-3 text-xs gap-1.5 shrink-0 transition-all ${
                      isPlaying ? 'bg-primary text-primary-foreground' : ''
                    }`}
                    onClick={() => handlePlaySound(item)}
                  >
                    <Play className={`h-3 w-3 ${isPlaying ? 'fill-current animate-pulse' : ''}`} />
                    <span>{isPlaying ? 'Играет' : 'Тест'}</span>
                  </Button>
                </div>
              );
            })}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
};
