import { useMemo, useRef } from 'react';
import JoditEditor from 'jodit-react';
import { API_ENDPOINTS } from '@/api/endpoints';

interface NewsEditorProps {
  value: string;
  onChange: (html: string) => void;
  placeholder?: string;
  height?: number;
}

/**
 * Rich-text editor for news articles. Stores HTML in `News.content`.
 *
 * Image uploads route through media-service so embedded images live in the
 * same storage backend as covers and other CMS assets. Jodit's default
 * uploader expects a JSON envelope; we wrap the media-service response into
 * the shape it wants.
 */
export function NewsEditor({ value, onChange, placeholder, height = 480 }: NewsEditorProps) {
  const editorRef = useRef(null);

  const config = useMemo(
    () => ({
      readonly: false,
      language: 'ru',
      placeholder: placeholder ?? 'Начните писать новость…',
      height,
      // Force toolbar popups (font/fontsize/color/paragraph/align/link/image/
      // video/table/copyformat) to mount on <body>. By default Jodit walks
      // up to the nearest position:fixed/absolute parent — Radix DialogContent
      // matches that AND clips with overflow-y-auto, so popups render but are
      // visually clipped, looking as if "the button does nothing".
      popupRoot: typeof document !== 'undefined' ? document.body : undefined,
      toolbarSticky: true,
      toolbarAdaptive: false,
      showTooltip: true,
      showTooltipDelay: 100,
      // Use the browser's native title-attribute tooltips. Jodit's custom
      // popup tooltips can be hidden by stacking contexts (e.g. inside our
      // Dialog), so the native ones are more reliable for end-users.
      useNativeTooltip: true,
      askBeforePasteHTML: false,
      askBeforePasteFromWord: false,
      defaultActionOnPaste: 'insert_clear_html',
      buttons: [
        'bold', 'italic', 'underline', 'strikethrough', 'eraser', '|',
        'ul', 'ol', '|',
        'font', 'fontsize', 'brush', '|',
        'paragraph', '|',
        'align', '|',
        'link', 'image', 'video', 'table', 'hr', '|',
        'indent', 'outdent', '|',
        'superscript', 'subscript', '|',
        'copyformat', 'selectall', '|',
        'undo', 'redo', '|',
        'fullsize', 'preview', 'source', 'print',
      ],
      buttonsMD: [
        'bold', 'italic', 'underline', '|',
        'ul', 'ol', '|',
        'font', 'fontsize', 'brush', '|',
        'paragraph', '|',
        'align', '|',
        'link', 'image', 'table', '|',
        'undo', 'redo', '|',
        'fullsize', 'source',
      ],
      buttonsSM: [
        'bold', 'italic', '|',
        'ul', 'ol', '|',
        'brush', '|',
        'paragraph', '|',
        'link', 'image', '|',
        'undo', 'redo', '|',
        'source',
      ],
      removeButtons: ['file', 'about', 'classSpan'],
      controls: {
        bold: {
          tooltip: 'Жирный текст (Ctrl+B)',
        },
        italic: {
          tooltip: 'Курсив (Ctrl+I)',
        },
        underline: {
          tooltip: 'Подчёркнутый (Ctrl+U)',
        },
        strikethrough: {
          tooltip: 'Зачёркнутый текст',
        },
        eraser: {
          tooltip: 'Очистить форматирование',
        },
        ul: {
          tooltip: 'Маркированный список',
        },
        ol: {
          tooltip: 'Нумерованный список',
        },
        font: {
          tooltip: 'Шрифт',
        },
        fontsize: {
          tooltip: 'Размер шрифта',
        },
        brush: {
          tooltip: 'Цвет текста / фона',
        },
        paragraph: {
          tooltip: 'Стиль абзаца (H1–H4, параграф, цитата)',
        },
        align: {
          tooltip: 'Выравнивание текста',
        },
        link: {
          tooltip: 'Вставить / редактировать ссылку',
        },
        image: {
          tooltip: 'Вставить изображение',
        },
        video: {
          tooltip: 'Вставить видео (YouTube, Vimeo)',
        },
        table: {
          tooltip: 'Вставить таблицу',
        },
        hr: {
          tooltip: 'Горизонтальная линия',
        },
        indent: {
          tooltip: 'Увеличить отступ',
        },
        outdent: {
          tooltip: 'Уменьшить отступ',
        },
        superscript: {
          tooltip: 'Верхний индекс',
        },
        subscript: {
          tooltip: 'Нижний индекс',
        },
        copyformat: {
          tooltip: 'Копировать формат',
        },
        selectall: {
          tooltip: 'Выделить всё (Ctrl+A)',
        },
        undo: {
          tooltip: 'Отменить (Ctrl+Z)',
        },
        redo: {
          tooltip: 'Повторить (Ctrl+Y)',
        },
        fullsize: {
          tooltip: 'Полноэкранный режим',
        },
        preview: {
          tooltip: 'Предпросмотр',
        },
        source: {
          tooltip: 'HTML-код',
        },
        print: {
          tooltip: 'Распечатать',
        },
      },
      uploader: {
        url: '/' + API_ENDPOINTS.mediaFiles + '/',
        format: 'json',
        method: 'POST',
        // Send the same cookies axios uses for JWT auth on upload XHR.
        withCredentials: true,
        prepareData: (formData: FormData) => {
          // Jodit names the field `files[0]` by default; media-service expects `file`.
          const original = formData.get('files[0]');
          if (original instanceof File) {
            formData.delete('files[0]');
            formData.append('file', original);
          }
          formData.append('scope', 'cms-news');
          formData.append('is_public', 'true');
          return formData;
        },
        isSuccess: (resp: any) => resp && (resp.url || resp.path || resp.id),
        getMessage: (resp: any) => resp?.detail || 'Upload failed',
        process: (resp: any) => ({
          files: [resp.url || resp.path],
          path: resp.url || resp.path,
          baseurl: '',
          error: 0,
          msg: 'ok',
        }),
        defaultHandlerSuccess: function (this: any, data: any) {
          // `this` is the Jodit editor instance when called by the uploader;
          // fall back to the ref if the binding context is lost.
          const editor: any = this?.selection ? this : (editorRef.current as any);
          if (!editor?.selection || !data?.files?.length) return;
          for (const url of data.files) {
            editor.selection.insertImage(url);
          }
        },
      },
      style: { font: '15px Inter, system-ui, sans-serif' },
    }),
    [height, placeholder],
  );

  // jodit-react re-mounts on every config object change, so memoize above.
  // We also disable the controlled-mode rerender by passing onBlur instead of
  // onChange for performance; onChange would fire on every keystroke and
  // reformat the editor content.
  return (
    <div className="news-editor-wrapper">
      <JoditEditor
        ref={editorRef}
        value={value}
        config={config as any}
        onBlur={(newContent) => onChange(newContent)}
      />
      <details className="group border-t border-border/50 bg-muted/20 px-4 py-2 text-xs text-muted-foreground">
        <summary className="cursor-pointer select-none font-semibold text-foreground/80 hover:text-primary">
          Подсказки по кнопкам редактора
        </summary>
        <div className="mt-3 grid gap-x-6 gap-y-1.5 sm:grid-cols-2 lg:grid-cols-3">
          <div><b>B</b> — жирный (Ctrl+B)</div>
          <div><b>I</b> — курсив (Ctrl+I)</div>
          <div><b>U</b> — подчёркнутый (Ctrl+U)</div>
          <div><b>S</b> — зачёркнутый</div>
          <div><b>Ластик</b> — очистить форматирование</div>
          <div><b>Списки</b> — маркированный / нумерованный</div>
          <div><b>A</b> — шрифт</div>
          <div><b>TI</b> — размер шрифта</div>
          <div><b>Капля</b> — цвет текста и фона</div>
          <div><b>¶</b> — стиль абзаца (H1–H4, цитата)</div>
          <div><b>Линии</b> — выравнивание текста</div>
          <div><b>Цепочка</b> — вставить / редактировать ссылку</div>
          <div><b>Картинка</b> — загрузить изображение</div>
          <div><b>Камера</b> — вставить видео (YouTube, Vimeo)</div>
          <div><b>Сетка</b> — вставить таблицу</div>
          <div><b>—</b> — горизонтальная линия</div>
          <div><b>Стрелки отступа</b> — увеличить / уменьшить отступ</div>
          <div><b>x²&nbsp;/&nbsp;x₂</b> — верхний / нижний индекс</div>
          <div><b>Кисть</b> — копировать формат</div>
          <div><b>Рамка</b> — выделить всё (Ctrl+A)</div>
          <div><b>↺ / ↻</b> — отменить (Ctrl+Z) / повторить (Ctrl+Y)</div>
          <div><b>↔</b> — полноэкранный режим</div>
          <div><b>Глаз</b> — предпросмотр</div>
          <div><b>&lt;/&gt;</b> — HTML-код</div>
          <div><b>Принтер</b> — распечатать</div>
        </div>
      </details>
    </div>
  );
}


