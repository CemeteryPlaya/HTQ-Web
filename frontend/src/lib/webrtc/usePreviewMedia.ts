/**
 * Предпросмотр «проверь камеру и звук» перед входом в конференцию.
 *
 * Вынесен из ConferencePage не ради красоты: здесь живёт инвариант, который
 * нельзя проверить, не подняв страницу целиком, — **устройства обязаны быть
 * отпущены, когда предпросмотр не нужен**. Нарушался он двумя способами
 * сразу, и оба выглядели для человека одинаково: горящая лампочка камеры.
 *
 * 1. Захват шёл при входе в комнату, до того как человек решил, заходит ли
 *    он в разговор вообще. Теперь нужно явное `active`.
 * 2. Очистка эффекта видела `previewStream` таким, каким он был на момент
 *    ЗАПУСКА эффекта, то есть `null` — поток появлялся позже, и на
 *    размонтировании останавливать было нечего. Камера продолжала работать
 *    на других страницах, пока не закроешь вкладку. Отсюда `streamRef`.
 *
 * Третья ловушка — `track.enabled = false`. Она гасит картинку, но
 * устройство держит открытым: индикатор продолжает гореть, и человек
 * справедливо считает, что его снимают. Поэтому выключение камеры здесь
 * пересобирает поток, а не глушит трек.
 */
import { useCallback, useEffect, useRef, useState } from 'react';

export interface PreviewMediaOptions {
  /** Человек явно включил предпросмотр. Без этого не захватывается ничего. */
  active: boolean;
  cam: boolean;
  mic: boolean;
  /** Вызывается, когда браузер отказал (нет разрешения, нет устройства). */
  onFailure?: (error: unknown) => void;
}

export interface PreviewMedia {
  stream: MediaStream | null;
  /** Открытые устройства: `''`, `'v'`, `'a'` или `'va'` — для тестов и отладки. */
  devices: string;
  stop: () => void;
}

export function usePreviewMedia({
  active, cam, mic, onFailure,
}: PreviewMediaOptions): PreviewMedia {
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [devices, setDevices] = useState('');

  const streamRef = useRef<MediaStream | null>(null);
  const devicesRef = useRef('');
  // Через ref, чтобы смена обработчика не пересобирала поток: заново
  // спрашивать камеру из-за нового замыкания — это лишняя вспышка индикатора.
  const onFailureRef = useRef(onFailure);
  useEffect(() => { onFailureRef.current = onFailure; }, [onFailure]);

  const stop = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    devicesRef.current = '';
    setStream(null);
    setDevices('');
  }, []);

  const wanted = active ? `${cam ? 'v' : ''}${mic ? 'a' : ''}` : '';

  useEffect(() => {
    if (!wanted) {
      stop();
      return;
    }
    if (devicesRef.current === wanted && streamRef.current) return;

    // Набор изменился — старый поток отпускаем целиком, иначе выключенная
    // камера осталась бы открытой внутри того же MediaStream.
    stop();
    devicesRef.current = wanted;

    let cancelled = false;

    void (async () => {
      try {
        const captured = await navigator.mediaDevices.getUserMedia({
          video: wanted.includes('v'),
          audio: wanted.includes('a'),
        });
        // Ушли со страницы, пока браузер спрашивал разрешение. Не
        // остановить здесь — значит оставить камеру включённой на странице,
        // которой уже нет.
        if (cancelled) {
          captured.getTracks().forEach((track) => track.stop());
          return;
        }
        streamRef.current = captured;
        setStream(captured);
        setDevices(wanted);
      } catch (err) {
        if (cancelled) return;
        devicesRef.current = '';
        onFailureRef.current?.(err);
      }
    })();

    return () => { cancelled = true; };
  }, [wanted, stop]);

  // Отдельно и последним: единственная задача — отпустить устройства при
  // уходе со страницы, что бы ни происходило в эффекте выше.
  useEffect(() => stop, [stop]);

  return { stream, devices, stop };
}
