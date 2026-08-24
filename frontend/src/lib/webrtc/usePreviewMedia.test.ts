/**
 * Предпросмотр перед входом в конференцию.
 *
 * Все проверки здесь — про одно: КОГДА устройства открыты и, главное, когда
 * отпущены. Баг, из-за которого хук появился, выглядел так: камера включалась
 * при входе в комнату (человек ещё не решил, заходить ли) и продолжала гореть
 * после ухода на другую страницу. Ни то, ни другое не ловилось ничем —
 * страница конференции в тест не поднимается.
 */
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { usePreviewMedia } from './usePreviewMedia';

interface FakeTrack { kind: string; readyState: string; stop: () => void }

function fakeStream(constraints: MediaStreamConstraints) {
  const tracks: FakeTrack[] = [];
  const add = (kind: string) => {
    const track: FakeTrack = {
      kind,
      readyState: 'live',
      stop: vi.fn(() => { track.readyState = 'ended'; }),
    };
    tracks.push(track);
  };
  if (constraints.video) add('video');
  if (constraints.audio) add('audio');
  return { getTracks: () => tracks, tracks } as unknown as MediaStream & { tracks: FakeTrack[] };
}

let getUserMedia: ReturnType<typeof vi.fn>;

beforeEach(() => {
  getUserMedia = vi.fn(async (constraints: MediaStreamConstraints) => fakeStream(constraints));
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: { getUserMedia },
  });
});

afterEach(() => vi.restoreAllMocks());

const opts = (over: Partial<Parameters<typeof usePreviewMedia>[0]> = {}) => ({
  active: false, cam: true, mic: true, ...over,
});

it('не трогает устройства, пока предпросмотр не включили явно', () => {
  renderHook(() => usePreviewMedia(opts()));
  expect(getUserMedia).not.toHaveBeenCalled();
});

it('захватывает только после явного включения', async () => {
  const { rerender, result } = renderHook((p) => usePreviewMedia(p), {
    initialProps: opts(),
  });
  expect(getUserMedia).not.toHaveBeenCalled();

  await act(async () => { rerender(opts({ active: true })); });

  expect(getUserMedia).toHaveBeenCalledWith({ video: true, audio: true });
  expect(result.current.stream).not.toBeNull();
});

describe('освобождение устройств', () => {
  it('останавливает треки при размонтировании — тот самый баг', async () => {
    const { result, unmount } = renderHook(() => usePreviewMedia(opts({ active: true })));
    await act(async () => {});

    const tracks = (result.current.stream as unknown as { tracks: FakeTrack[] }).tracks;
    expect(tracks).toHaveLength(2);

    unmount();

    // Камера и микрофон обязаны быть отпущены: иначе индикатор продолжает
    // гореть на странице, которой уже нет.
    expect(tracks.every((t) => t.readyState === 'ended')).toBe(true);
  });

  it('останавливает поток, приехавший уже после ухода со страницы', async () => {
    let release: (s: MediaStream) => void = () => {};
    getUserMedia.mockImplementation(
      () => new Promise<MediaStream>((resolve) => { release = resolve; })
    );

    const { unmount } = renderHook(() => usePreviewMedia(opts({ active: true })));
    unmount();   // человек ушёл, пока браузер спрашивал разрешение

    const late = fakeStream({ video: true, audio: true });
    await act(async () => { release(late); });

    expect((late as unknown as { tracks: FakeTrack[] }).tracks
      .every((t) => t.readyState === 'ended')).toBe(true);
  });

  it('отпускает устройства, когда предпросмотр выключают', async () => {
    const { rerender, result } = renderHook((p) => usePreviewMedia(p), {
      initialProps: opts({ active: true }),
    });
    await act(async () => {});
    const tracks = (result.current.stream as unknown as { tracks: FakeTrack[] }).tracks;

    await act(async () => { rerender(opts({ active: false })); });

    expect(tracks.every((t) => t.readyState === 'ended')).toBe(true);
    expect(result.current.stream).toBeNull();
  });
});

describe('переключение камеры и микрофона', () => {
  it('выключенная камера действительно отпускается, а не глушится', async () => {
    const { rerender, result } = renderHook((p) => usePreviewMedia(p), {
      initialProps: opts({ active: true }),
    });
    await act(async () => {});
    const first = (result.current.stream as unknown as { tracks: FakeTrack[] }).tracks;

    await act(async () => { rerender(opts({ active: true, cam: false })); });

    // Старый поток остановлен целиком, а не помечен enabled=false: иначе
    // устройство осталось бы открытым и лампочка продолжала бы гореть.
    expect(first.every((t) => t.readyState === 'ended')).toBe(true);
    expect(getUserMedia).toHaveBeenLastCalledWith({ video: false, audio: true });
    expect(result.current.devices).toBe('a');
  });

  it('не пересобирает поток, если набор устройств не менялся', async () => {
    const { rerender } = renderHook((p) => usePreviewMedia(p), {
      initialProps: opts({ active: true }),
    });
    await act(async () => {});
    expect(getUserMedia).toHaveBeenCalledTimes(1);

    // Тот же набор, но новая ссылка на onFailure — лишний перезахват здесь
    // означал бы лишнюю вспышку индикатора камеры.
    await act(async () => {
      rerender(opts({ active: true, onFailure: () => {} }));
    });
    expect(getUserMedia).toHaveBeenCalledTimes(1);
  });

  it('ничего не открывает, когда выключены оба', async () => {
    renderHook(() => usePreviewMedia(opts({ active: true, cam: false, mic: false })));
    await act(async () => {});
    expect(getUserMedia).not.toHaveBeenCalled();
  });
});

it('сообщает об отказе и не оставляет висящего состояния', async () => {
  const denied = new DOMException('Permission denied', 'NotAllowedError');
  getUserMedia.mockRejectedValue(denied);
  const onFailure = vi.fn();

  const { result } = renderHook(() => usePreviewMedia(opts({ active: true, onFailure })));
  await act(async () => {});

  expect(onFailure).toHaveBeenCalledWith(denied);
  expect(result.current.stream).toBeNull();
  expect(result.current.devices).toBe('');
});
