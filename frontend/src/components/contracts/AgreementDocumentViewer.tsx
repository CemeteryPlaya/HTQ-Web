/**
 * Просмотр скана договора ВНУТРИ карточки — вместо «открыть в новой вкладке».
 *
 * Зачем: договор не пробегают глазами, его изучают — сверяют предмет с
 * названием, сумму в тексте с суммой в реквизитах, срок в пункте со сроком в
 * карточке. Пока документ открывался отдельной вкладкой, каждая такая сверка
 * стоила переключения туда-обратно, и реквизиты приходилось держать в голове.
 *
 * Отсюда два режима:
 *
 * * **встроенный** — документ прямо в карточке, сразу под реквизитами;
 * * **во весь экран** — диалог, где рядом с документом стоит колонка
 *   реквизитов. Это и есть «изучать»: читаешь пункт и тут же видишь, что
 *   записано в системе.
 *
 * Способ показа выбирается по mime, который приезжает вместе со ссылкой
 * (``GET agreements/<id>/file-url``): PDF — во фрейм, картинка — в ``img`` со
 * своим зумом. Всё остальное (docx, xlsx) браузер отрисовать не может, и
 * честнее сказать это прямо, чем показывать пустой фрейм.
 *
 * ⚠️ Ссылка подписанная и живёт недолго, поэтому она НЕ кладётся в
 * долгоживущий кэш: ``staleTime`` короче TTL, а диалог перезапрашивает её при
 * открытии. Иначе «читать» на давно открытой странице упиралось бы в 403 от
 * хранилища.
 */
import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  AlertCircle,
  Download,
  ExternalLink,
  FileText,
  Loader2,
  Maximize2,
  Minus,
  Plus,
  RotateCcw,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog';
import { Separator } from '@/components/ui/separator';
import { contractsApi } from '@/api/contracts';

/** Ссылка живёт 10 минут; держим её в кэше заведомо меньше. */
const URL_STALE_MS = 4 * 60 * 1000;

const ZOOM_MIN = 0.25;
const ZOOM_MAX = 4;
const ZOOM_STEP = 0.25;

export interface AgreementDocumentViewerProps {
  agreementId: number;
  /** Есть ли вообще что показывать — из `agreement.file_id`. */
  hasFile: boolean;
  /** Реквизиты для колонки в полноэкранном режиме. */
  summary?: { label: string; value: string }[];
  title?: string;
}

function humanSize(bytes: number): string {
  if (!bytes) return '';
  const units = ['Б', 'КБ', 'МБ', 'ГБ'];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value >= 10 || unit === 0 ? 0 : 1)} ${units[unit]}`;
}

type Renderable = 'pdf' | 'image' | 'none';

/** Чем показывать. Расширение — запасной путь: у старых файлов mime пустой.
 *
 * SVG исключён намеренно и ровно по той же причине, по которой его исключает
 * сервер (``_INLINE_MIME_DENYLIST`` в apps/media_files/views.py): SVG умеет
 * нести <script>, поэтому media отдаёт его как attachment, а не inline.
 * Показывать его здесь — значит спорить с этим решением. */
function renderableOf(mime: string, name: string): Renderable {
  const m = mime.toLowerCase().split(';', 1)[0].trim();
  if (m === 'image/svg+xml') return 'none';
  if (m.includes('pdf')) return 'pdf';
  if (m.startsWith('image/')) return 'image';
  const ext = name.toLowerCase().split('.').pop() ?? '';
  if (ext === 'pdf') return 'pdf';
  if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'tif', 'tiff'].includes(ext)) {
    return 'image';
  }
  return 'none';
}

const AgreementDocumentViewer = ({
  agreementId,
  hasFile,
  summary = [],
  title = 'Документ договора',
}: AgreementDocumentViewerProps) => {
  const [fullscreen, setFullscreen] = useState(false);
  const [zoom, setZoom] = useState(1);

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['contracts', 'agreement', agreementId, 'file-url'],
    queryFn: () => contractsApi.getAgreementFileUrl(agreementId).then((r) => r.data),
    enabled: hasFile,
    staleTime: URL_STALE_MS,
    // Ссылка протухает по времени, а не по данным: обновлять её при каждом
    // фокусе окна незачем, но и переиспользовать вечно нельзя.
    refetchOnWindowFocus: false,
  });

  // Диалог открывается на уже загруженной странице, где ссылке может быть
  // много минут. Перезапрашиваем, иначе хранилище ответит 403.
  useEffect(() => {
    if (fullscreen) {
      setZoom(1);
      void refetch();
    }
  }, [fullscreen, refetch]);

  if (!hasFile) return null;

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center rounded-lg border bg-muted/20">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (isError || !data?.url) {
    return (
      <div className="flex h-40 flex-col items-center justify-center gap-3 rounded-lg border bg-muted/20 text-center">
        <AlertCircle className="h-6 w-6 text-muted-foreground" />
        <p className="text-sm text-muted-foreground">
          Не удалось получить ссылку на документ.
        </p>
        <Button size="sm" variant="outline" onClick={() => void refetch()}>
          <RotateCcw className="mr-1.5 h-4 w-4" />
          Повторить
        </Button>
      </div>
    );
  }

  const { url, name, mime, size } = data;
  const renderable = renderableOf(mime ?? '', name ?? '');

  const toolbar = (
    <div className="flex flex-wrap items-center gap-2">
      {renderable === 'image' && (
        <div className="flex items-center gap-1 rounded-md border p-0.5">
          <Button
            size="icon"
            variant="ghost"
            className="h-7 w-7"
            aria-label="Уменьшить"
            disabled={zoom <= ZOOM_MIN}
            onClick={() => setZoom((z) => Math.max(ZOOM_MIN, z - ZOOM_STEP))}
          >
            <Minus className="h-4 w-4" />
          </Button>
          <span className="w-12 text-center text-xs tabular-nums text-muted-foreground">
            {Math.round(zoom * 100)}%
          </span>
          <Button
            size="icon"
            variant="ghost"
            className="h-7 w-7"
            aria-label="Увеличить"
            disabled={zoom >= ZOOM_MAX}
            onClick={() => setZoom((z) => Math.min(ZOOM_MAX, z + ZOOM_STEP))}
          >
            <Plus className="h-4 w-4" />
          </Button>
        </div>
      )}
      <Button size="sm" variant="outline" asChild>
        <a href={url} target="_blank" rel="noopener noreferrer">
          <ExternalLink className="mr-1.5 h-4 w-4" />
          В новой вкладке
        </a>
      </Button>
      <Button size="sm" variant="outline" asChild>
        {/* Приватный файл media отдаёт своим же origin
            (`/api/media/v1/files/<id>?sig=`), поэтому `download` тут
            срабатывает и сохраняет под настоящим именем. У публичного файла
            ссылка ведёт прямо в S3, и там атрибут игнорируется — файл просто
            откроется; это допустимо, скан договора всегда приватный. */}
        <a href={url} download={name || undefined}>
          <Download className="mr-1.5 h-4 w-4" />
          Скачать
        </a>
      </Button>
    </div>
  );

  const body = (fill: boolean) => {
    const frameClass = fill ? 'h-full w-full' : 'h-[70vh] max-h-[820px] w-full';

    if (renderable === 'pdf') {
      return (
        <iframe
          // #view=FitH — открыть по ширине: договор читают по строкам, а не
          // разглядывают страницу целиком.
          src={`${url}#view=FitH`}
          title={name || title}
          className={`${frameClass} rounded-lg border bg-muted/10`}
        />
      );
    }

    if (renderable === 'image') {
      return (
        <div
          className={`${frameClass} overflow-auto rounded-lg border bg-muted/10 p-2`}
        >
          <img
            src={url}
            alt={name || title}
            className="mx-auto block origin-top transition-transform"
            style={{ transform: `scale(${zoom})`, transformOrigin: 'top center' }}
          />
        </div>
      );
    }

    return (
      <div
        className={`${frameClass} flex flex-col items-center justify-center gap-3 rounded-lg border bg-muted/20 text-center`}
      >
        <FileText className="h-8 w-8 text-muted-foreground" />
        <div>
          <p className="text-sm font-medium">{name || 'Документ'}</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Этот формат браузер не показывает — откройте его в новой вкладке
            или скачайте.
          </p>
        </div>
      </div>
    );
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
          <span className="truncate text-sm font-medium">{name || title}</span>
          {size ? (
            <span className="shrink-0 text-xs text-muted-foreground">
              {humanSize(size)}
            </span>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" onClick={() => setFullscreen(true)}>
            <Maximize2 className="mr-1.5 h-4 w-4" />
            Читать
          </Button>
          {toolbar}
        </div>
      </div>

      {body(false)}

      <Dialog open={fullscreen} onOpenChange={setFullscreen}>
        <DialogContent
          className="flex h-[95vh] w-[98vw] max-w-[98vw] flex-col gap-3 p-4 sm:max-w-[98vw]"
        >
          <div className="flex flex-wrap items-center justify-between gap-3 pr-8">
            <DialogTitle className="flex min-w-0 items-center gap-2 text-base">
              <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
              <span className="truncate">{name || title}</span>
            </DialogTitle>
            {toolbar}
          </div>

          <div className="flex min-h-0 flex-1 gap-4">
            <div className="min-w-0 flex-1">{body(true)}</div>

            {summary.length > 0 && (
              <>
                <Separator orientation="vertical" className="hidden lg:block" />
                {/* Реквизиты рядом с текстом — ради этого весь режим и нужен:
                    прочитал пункт и тут же сверил с тем, что в системе. */}
                <aside className="hidden w-72 shrink-0 overflow-y-auto lg:block">
                  <p className="mb-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Реквизиты в системе
                  </p>
                  <dl className="space-y-3">
                    {summary.map((row) => (
                      <div key={row.label}>
                        <dt className="text-xs text-muted-foreground">
                          {row.label}
                        </dt>
                        <dd className="break-words text-sm font-medium">
                          {row.value || '—'}
                        </dd>
                      </div>
                    ))}
                  </dl>
                </aside>
              </>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default AgreementDocumentViewer;
