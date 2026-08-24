import { useMemo, useRef } from 'react';
import { useTranslation } from 'react-i18next';
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
  const { t, i18n } = useTranslation();
  const editorRef = useRef(null);

  const config = useMemo(
    () => ({
      readonly: false,
      language: i18n.language?.startsWith('en') ? 'en' : 'ru',
      placeholder: placeholder ?? t('news.editor.placeholder'),
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
          tooltip: t('news.editor.tooltips.bold'),
        },
        italic: {
          tooltip: t('news.editor.tooltips.italic'),
        },
        underline: {
          tooltip: t('news.editor.tooltips.underline'),
        },
        strikethrough: {
          tooltip: t('news.editor.tooltips.strikethrough'),
        },
        eraser: {
          tooltip: t('news.editor.tooltips.eraser'),
        },
        ul: {
          tooltip: t('news.editor.tooltips.ul'),
        },
        ol: {
          tooltip: t('news.editor.tooltips.ol'),
        },
        font: {
          tooltip: t('news.editor.tooltips.font'),
        },
        fontsize: {
          tooltip: t('news.editor.tooltips.fontsize'),
        },
        brush: {
          tooltip: t('news.editor.tooltips.color'),
        },
        paragraph: {
          tooltip: t('news.editor.tooltips.paragraph'),
        },
        align: {
          tooltip: t('news.editor.tooltips.align'),
        },
        link: {
          tooltip: t('news.editor.tooltips.link'),
        },
        image: {
          tooltip: t('news.editor.tooltips.image'),
        },
        video: {
          tooltip: t('news.editor.tooltips.video'),
        },
        table: {
          tooltip: t('news.editor.tooltips.table'),
        },
        hr: {
          tooltip: t('news.editor.tooltips.hr'),
        },
        indent: {
          tooltip: t('news.editor.tooltips.indent'),
        },
        outdent: {
          tooltip: t('news.editor.tooltips.outdent'),
        },
        superscript: {
          tooltip: t('news.editor.tooltips.superscript'),
        },
        subscript: {
          tooltip: t('news.editor.tooltips.subscript'),
        },
        copyformat: {
          tooltip: t('news.editor.tooltips.copyformat'),
        },
        selectall: {
          tooltip: t('news.editor.tooltips.selectall'),
        },
        undo: {
          tooltip: t('news.editor.tooltips.undo'),
        },
        redo: {
          tooltip: t('news.editor.tooltips.redo'),
        },
        fullsize: {
          tooltip: t('news.editor.tooltips.fullsize'),
        },
        preview: {
          tooltip: t('news.editor.tooltips.preview'),
        },
        source: {
          tooltip: t('news.editor.tooltips.source'),
        },
        print: {
          tooltip: t('news.editor.tooltips.print'),
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
    [height, placeholder, t, i18n.language],
  );

  // Подсказки по панели: подпись кнопки бывает символом (B, ¶, </>), а бывает
  // словом — тогда переводится и она, и описание.
  const hints = useMemo(
    () => [
      { term: 'B', descKey: 'news.editor.hints.bold' },
      { term: 'I', descKey: 'news.editor.hints.italic' },
      { term: 'U', descKey: 'news.editor.hints.underline' },
      { term: 'S', descKey: 'news.editor.hints.strikethrough' },
      { term: t('news.editor.terms.eraser'), descKey: 'news.editor.hints.clearFormat' },
      { term: t('news.editor.terms.lists'), descKey: 'news.editor.hints.lists' },
      { term: 'A', descKey: 'news.editor.hints.font' },
      { term: 'TI', descKey: 'news.editor.hints.fontsize' },
      { term: t('news.editor.terms.drop'), descKey: 'news.editor.hints.color' },
      { term: '¶', descKey: 'news.editor.hints.paragraph' },
      { term: t('news.editor.terms.lines'), descKey: 'news.editor.hints.align' },
      { term: t('news.editor.terms.chain'), descKey: 'news.editor.hints.link' },
      { term: t('news.editor.terms.picture'), descKey: 'news.editor.hints.image' },
      { term: t('news.editor.terms.camera'), descKey: 'news.editor.hints.video' },
      { term: t('news.editor.terms.grid'), descKey: 'news.editor.hints.table' },
      { term: '—', descKey: 'news.editor.hints.hr' },
      { term: t('news.editor.terms.indentArrows'), descKey: 'news.editor.hints.indent' },
      { term: 'x² / x₂', descKey: 'news.editor.hints.script' },
      { term: t('news.editor.terms.brush'), descKey: 'news.editor.hints.copyformat' },
      { term: t('news.editor.terms.frame'), descKey: 'news.editor.hints.selectall' },
      { term: '↺ / ↻', descKey: 'news.editor.hints.undoRedo' },
      { term: '↔', descKey: 'news.editor.hints.fullsize' },
      { term: t('news.editor.terms.eye'), descKey: 'news.editor.hints.preview' },
      { term: '</>', descKey: 'news.editor.hints.source' },
      { term: t('news.editor.terms.printer'), descKey: 'news.editor.hints.print' },
    ],
    [t],
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
          {t('news.editor.hintsTitle')}
        </summary>
        <div className="mt-3 grid gap-x-6 gap-y-1.5 sm:grid-cols-2 lg:grid-cols-3">
          {hints.map((h) => (
            <div key={h.descKey}>
              <b>{h.term}</b> — {t(h.descKey)}
            </div>
          ))}
        </div>
      </details>
    </div>
  );
}


