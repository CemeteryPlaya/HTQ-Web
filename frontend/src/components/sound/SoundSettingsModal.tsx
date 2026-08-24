import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
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
  updateKindSettings,
  subscribeSoundSettings,
  playSound,
  type SoundKind,
  type SoundSettings,
} from '@/lib/sound/soundService';

interface SoundItem {
  /** Вид сигнала — он же ключ воспроизведения и часть ключа перевода. */
  kind: SoundKind;
  nameKey: string;
  nameDefault: string;
  descriptionKey: string;
  descriptionDefault: string;
  icon: React.ElementType;
  color: string;
}

/** Порядок здесь — порядок в списке предпрослушивания: сгруппировано по
 *  источнику (мессенджер, календарь, сроки, система). */
const SOUND_PRESETS: SoundItem[] = [
  {
    kind: 'messenger',
    nameKey: 'sound.preset.messengerChime',
    nameDefault: 'Тёплая калимба',
    descriptionKey: 'sound.preset.messengerChimeHint',
    descriptionDefault: 'Входящее сообщение (восходящий интервал E5 → A5)',
    icon: MessageSquare,
    color: 'text-cyan-500 bg-cyan-500/10 border-cyan-500/20',
  },
  {
    kind: 'messenger-active',
    nameKey: 'sound.preset.messengerPop',
    nameDefault: 'Капля росы',
    descriptionKey: 'sound.preset.messengerPopHint',
    descriptionDefault: 'Мягкий бульк для чата, который сейчас открыт',
    icon: MessageSquare,
    color: 'text-blue-500 bg-blue-500/10 border-blue-500/20',
  },
  {
    kind: 'meeting',
    nameKey: 'sound.preset.meeting',
    nameDefault: 'Колокольчик созвона',
    descriptionKey: 'sound.preset.meetingHint',
    descriptionDefault: 'Встреча вот-вот начнётся',
    icon: Video,
    color: 'text-indigo-500 bg-indigo-500/10 border-indigo-500/20',
  },
  {
    kind: 'event',
    nameKey: 'sound.preset.event',
    nameDefault: 'Событие в календаре',
    descriptionKey: 'sound.preset.eventHint',
    descriptionDefault: 'Вас пригласили на событие или изменили его',
    icon: Calendar,
    color: 'text-emerald-500 bg-emerald-500/10 border-emerald-500/20',
  },
  {
    kind: 'deadline',
    nameKey: 'sound.preset.deadline',
    nameDefault: 'Спокойный пульс',
    descriptionKey: 'sound.preset.deadlineHint',
    descriptionDefault: 'Срок задачи приближается',
    icon: Clock,
    color: 'text-amber-500 bg-amber-500/10 border-amber-500/20',
  },
  {
    kind: 'deadline-urgent',
    nameKey: 'sound.preset.deadlineUrgent',
    nameDefault: 'Срочный сигнал',
    descriptionKey: 'sound.preset.deadlineUrgentHint',
    descriptionDefault: 'Срок истекает сегодня или уже прошёл',
    icon: AlertTriangle,
    color: 'text-rose-500 bg-rose-500/10 border-rose-500/20',
  },
  {
    kind: 'system',
    nameKey: 'sound.preset.system',
    nameDefault: 'Хрустальный перелив',
    descriptionKey: 'sound.preset.systemHint',
    descriptionDefault: 'Остальные уведомления платформы',
    icon: Sparkles,
    color: 'text-purple-500 bg-purple-500/10 border-purple-500/20',
  },
];

export const SoundSettingsModal: React.FC<{ trigger?: React.ReactNode }> = ({ trigger }) => {
  const { t } = useTranslation();
  const [settings, setSettings] = useState<SoundSettings>(getSoundSettings);
  const [activeSoundId, setActiveSoundId] = useState<SoundKind | null>(null);

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
    setActiveSoundId(sound.kind);
    // bypassThrottle — предпрослушивание не должно ни глохнуть само, ни
    // съедать окно, за которым придёт настоящее уведомление.
    playSound(sound.kind, { bypassThrottle: true });
    setTimeout(() => {
      setActiveSoundId((prev) => (prev === sound.kind ? null : prev));
    }, 450);
  };

  return (
    <Dialog>
      <DialogTrigger asChild>
        {trigger || (
          <Button variant="ghost" size="sm" className="gap-2 text-xs h-8">
            <Volume2 className="h-4 w-4" />
            <span>{t('sound.title', 'Звуки уведомлений')}</span>
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
              <DialogTitle className="text-lg">{t('sound.title', 'Звуки уведомлений')}</DialogTitle>
              <DialogDescription className="text-xs text-muted-foreground mt-0.5">
                {t('sound.description', 'Настройка и предпрослушивание звуков мессенджера, календаря и задач')}
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
                <span>{t('sound.enabled', 'Звуковые сигналы')}</span>
              </Label>
              <p className="text-xs text-muted-foreground">
                {t('sound.enabledHint', 'Воспроизведение аудио при входящих сообщениях и событиях')}
              </p>
            </div>
            <Switch checked={settings.enabled} onCheckedChange={handleToggle} />
          </div>

          <div className="space-y-2 pt-2 border-t">
            <div className="flex justify-between text-xs text-muted-foreground font-medium">
              <span>{t('sound.volume', 'Общая громкость')}</span>
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
            {t('sound.presets', 'Каждый сигнал по отдельности')}
          </h4>

          <div className="grid grid-cols-1 gap-2">
            {SOUND_PRESETS.map((item) => {
              const Icon = item.icon;
              const isPlaying = activeSoundId === item.kind;
              const own = settings.kinds[item.kind];
              // Персональный регулятор бессмысленно крутить при выключенном
              // общем звуке или выключенном самом сигнале — но сам сигнал
              // выключить можно всегда.
              const sliderDisabled = !settings.enabled || !own.enabled;

              return (
                <div
                  key={item.kind}
                  className={`rounded-xl border p-3 transition-all duration-200 ${
                    isPlaying
                      ? 'border-primary/50 bg-primary/5 shadow-sm'
                      : 'border-border/60 hover:border-border'
                  }`}
                >
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex items-center gap-3 min-w-0">
                      <div
                        className={`p-2 rounded-lg border shrink-0 transition-transform ${item.color} ${
                          isPlaying ? 'scale-110' : ''
                        } ${own.enabled ? '' : 'opacity-40'}`}
                      >
                        <Icon className="h-4 w-4" />
                      </div>
                      <div className="min-w-0">
                        <div className="text-sm font-medium leading-none truncate">
                          {t(item.nameKey, item.nameDefault)}
                        </div>
                        <div className="text-xs text-muted-foreground truncate mt-1">
                          {t(item.descriptionKey, item.descriptionDefault)}
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center gap-2 shrink-0">
                      <Button
                        size="sm"
                        variant={isPlaying ? 'default' : 'outline'}
                        className="h-8 px-3 text-xs gap-1.5"
                        onClick={() => handlePlaySound(item)}
                      >
                        <Play className={`h-3 w-3 ${isPlaying ? 'fill-current animate-pulse' : ''}`} />
                        <span>{isPlaying ? t('sound.playing', 'Играет') : t('sound.test', 'Тест')}</span>
                      </Button>
                      <Switch
                        checked={own.enabled}
                        disabled={!settings.enabled}
                        aria-label={t('sound.kindEnabled', 'Включить этот сигнал')}
                        onCheckedChange={(enabled) =>
                          updateKindSettings(item.kind, { enabled })
                        }
                      />
                    </div>
                  </div>

                  <div className="flex items-center gap-3 mt-3 pl-1">
                    <Slider
                      value={[Math.round(own.volume * 100)]}
                      min={0}
                      max={100}
                      step={5}
                      disabled={sliderDisabled}
                      aria-label={t('sound.kindVolume', 'Громкость сигнала')}
                      onValueChange={([value]) =>
                        updateKindSettings(item.kind, { volume: value / 100 })
                      }
                      className="flex-1"
                    />
                    <span className="text-xs text-muted-foreground tabular-nums w-10 text-right">
                      {Math.round(own.volume * 100)}%
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
};
