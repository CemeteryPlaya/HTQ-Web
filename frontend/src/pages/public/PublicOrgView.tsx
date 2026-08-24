/**
 * Public org view - no auth required, accessed via shareable token.
 *
 * The token is consumed once by the backend. RU/EN switching uses only the
 * tree variants returned by that first response, so one-time links do not make
 * a second consume request when the language changes.
 */
import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ReactFlowProvider } from '@xyflow/react';
import { ChevronLeft, Languages } from 'lucide-react';

import { EmployeeDetailDrawer } from '@/components/hr/EmployeeDetailDrawer';
import { OrgChart, type OrgRawNode } from '@/components/hr/OrgChart';
import { ShareWatermark, type WatermarkPayload } from '@/components/share-link/ShareWatermark';
import { Button } from '@/components/ui/button';
import i18n from '@/i18n';

type OrgLanguage = 'ru' | 'en';
type OrgTree = { nodes: any[]; edges: any[] };

interface OrgData {
  label: string | null;
  max_level: number;
  default_language?: OrgLanguage;
  generated_at: string | null;
  watermark: WatermarkPayload | null;
  tree: OrgTree;
  translations?: {
    en?: {
      tree?: OrgTree;
    };
  };
}

type ViewState = 'loading' | 'error' | 'gone' | 'ok';

const TEXT: Record<OrgLanguage, {
  linkNotFound: string;
  linkExpired: string;
  unavailable: string;
  genericError: string;
  badResponse: string;
  networkError: string;
  loading: string;
  accessDenied: string;
  backHome: string;
  publicLabel: string;
  title: string;
  restricted: string;
  generated: string;
  emptyTree: string;
}> = {
  ru: {
    linkNotFound: 'Ссылка не найдена или недействительна.',
    linkExpired: 'Эта ссылка уже была использована или истекла.',
    unavailable: 'Доступ недоступен',
    genericError: 'Произошла ошибка. Обратитесь к отправителю ссылки.',
    badResponse: 'Сервер вернул некорректный ответ. Свяжитесь с отправителем ссылки.',
    networkError: 'Не удалось подключиться к серверу.',
    loading: 'Загрузка структуры...',
    accessDenied: 'Доступ недоступен',
    backHome: 'На главную',
    publicLabel: 'Публичный просмотр оргструктуры',
    title: 'Структура организации',
    restricted: 'Просмотр ограничен. Данные доступны только по этой ссылке.',
    generated: 'Сгенерировано',
    emptyTree: 'В этой ссылке нет доступных элементов оргструктуры. Создайте новую ссылку без ограничения уровня.',
  },
  en: {
    linkNotFound: 'The link was not found or is not valid.',
    linkExpired: 'This link has already been used or has expired.',
    unavailable: 'Access unavailable',
    genericError: 'Something went wrong. Contact the link sender.',
    badResponse: 'The server returned an invalid response. Contact the link sender.',
    networkError: 'Could not connect to the server.',
    loading: 'Loading org chart...',
    accessDenied: 'Access unavailable',
    backHome: 'Home',
    publicLabel: 'Public org chart view',
    title: 'Organization Structure',
    restricted: 'View is restricted. Data is available only through this link.',
    generated: 'Generated',
    emptyTree: 'This link has no visible org chart items. Create a new link without a level limit.',
  },
};

const LOGO_SRC = '/images/logo.webp';

function buildConsumeUrl(token: string): string {
  const raw = (import.meta.env.VITE_API_BASE_URL ?? '/api').toString();
  const base = raw.replace(/\/+$/, '');
  return `${base}/hr/v1/public/org/${encodeURIComponent(token)}`;
}

/**
 * Язык до того, как приехал ответ: у гостя нет профиля, поэтому берём язык
 * интерфейса (i18n сам определил его по браузеру). Дальше язык диктует уже
 * сама ссылка — `default_language` из полезной нагрузки.
 */
function guestLanguage(): OrgLanguage {
  return normalizeLanguage(i18n.language?.split('-')[0]);
}

function normalizeLanguage(value: unknown): OrgLanguage {
  return value === 'en' ? 'en' : 'ru';
}

function GuestHeader({ label, lang }: { label?: string | null; lang: OrgLanguage }) {
  const text = TEXT[lang];

  return (
    <header className="shrink-0 border-b bg-card">
      <div className="mx-auto flex h-14 max-w-7xl items-center gap-2 px-3 sm:gap-4 sm:px-6">
        <Link
          to="/"
          className="flex min-w-0 flex-shrink-0 items-center gap-2 text-sm font-semibold text-foreground hover:opacity-80"
        >
          <img src={LOGO_SRC} alt="" className="h-7 w-7 object-contain" />
          <span className="hidden sm:inline">Hi-Tech Group</span>
        </Link>
        <div className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
          <span className="hidden md:inline">{text.publicLabel}</span>
          {label ? <span className="truncate md:ml-1 md:inline"> {label}</span> : null}
        </div>
        <Button asChild variant="ghost" size="sm" className="ml-auto h-8 flex-shrink-0 gap-1.5 px-2 sm:px-3">
          <Link to="/">
            <ChevronLeft className="h-4 w-4" />
            <span className="hidden sm:inline">{text.backHome}</span>
          </Link>
        </Button>
      </div>
    </header>
  );
}

function LanguageToggle({
  value,
  hasEnglish,
  onChange,
}: {
  value: OrgLanguage;
  hasEnglish: boolean;
  onChange: (lang: OrgLanguage) => void;
}) {
  return (
    <div className="flex items-center gap-1 rounded-md border bg-background p-0.5">
      <Languages className="ml-1.5 h-3.5 w-3.5 text-muted-foreground" aria-hidden />
      {(['ru', 'en'] as OrgLanguage[]).map((lang) => {
        const disabled = lang === 'en' && !hasEnglish;
        return (
          <button
            key={lang}
            type="button"
            disabled={disabled}
            onClick={() => onChange(lang)}
            className={`h-7 rounded px-2 text-xs font-medium transition ${
              value === lang
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40'
            }`}
          >
            {lang.toUpperCase()}
          </button>
        );
      })}
    </div>
  );
}

const PublicOrgView = () => {
  const { token } = useParams<{ token: string }>();
  const [state, setState] = useState<ViewState>('loading');
  const [data, setData] = useState<OrgData | null>(null);
  const [errorMsg, setErrorMsg] = useState<string>('');
  const [currentLang, setCurrentLang] = useState<OrgLanguage>('ru');
  const [selected, setSelected] = useState<OrgRawNode | null>(null);

  useEffect(() => {
    if (!token) {
      setErrorMsg(TEXT[guestLanguage()].linkNotFound);
      setState('gone');
      return;
    }

    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(buildConsumeUrl(token), {
          method: 'GET',
          credentials: 'omit',
          headers: { Accept: 'application/json' },
        });
        if (cancelled) return;

        if (res.status === 404 || res.status === 410) {
          const gone = TEXT[guestLanguage()];
          setErrorMsg(res.status === 404 ? gone.linkNotFound : gone.linkExpired);
          setState('gone');
          return;
        }
        if (!res.ok) {
          setErrorMsg(TEXT[guestLanguage()].genericError);
          setState('error');
          return;
        }

        const ct = res.headers.get('content-type') ?? '';
        if (!ct.includes('application/json')) {
          setErrorMsg(TEXT[guestLanguage()].badResponse);
          setState('error');
          return;
        }

        const json: OrgData = await res.json();
        const hasEnglish = Boolean(json.translations?.en?.tree);
        const requestedLanguage = normalizeLanguage(json.default_language);
        setData(json);
        setCurrentLang(requestedLanguage === 'en' && hasEnglish ? 'en' : 'ru');
        setState('ok');
      } catch {
        if (!cancelled) {
          setErrorMsg(TEXT[guestLanguage()].networkError);
          setState('error');
        }
      }
    })();

    return () => { cancelled = true; };
  }, [token]);

  if (state === 'loading') {
    return (
      <div className="flex min-h-[100dvh] flex-col bg-background">
        <GuestHeader lang={guestLanguage()} />
        <div className="flex flex-1 items-center justify-center">
          <div className="text-sm text-muted-foreground">{TEXT[guestLanguage()].loading}</div>
        </div>
      </div>
    );
  }

  if (state === 'gone' || state === 'error') {
    return (
      <div className="flex min-h-[100dvh] flex-col bg-background">
        <GuestHeader lang={guestLanguage()} />
        <div className="flex flex-1 items-center justify-center p-6">
          <div className="max-w-sm space-y-3 text-center">
            <h1 className="text-lg font-semibold">{TEXT[guestLanguage()].accessDenied}</h1>
            <p className="text-sm text-muted-foreground">{errorMsg}</p>
            <Button asChild variant="outline" size="sm" className="mt-4">
              <Link to="/">{TEXT[guestLanguage()].backHome}</Link>
            </Button>
          </div>
        </div>
      </div>
    );
  }

  const hasEnglishTree = Boolean(data?.translations?.en?.tree);
  const viewLang: OrgLanguage = currentLang === 'en' && hasEnglishTree ? 'en' : 'ru';
  const text = TEXT[viewLang];
  const activeTree: OrgTree =
    viewLang === 'en' && data?.translations?.en?.tree
      ? data.translations.en.tree
      : data?.tree ?? { nodes: [], edges: [] };

  return (
    <div className="flex h-[100dvh] flex-col overflow-hidden bg-background">
      <GuestHeader label={data?.label} lang={viewLang} />

      <div className="shrink-0 border-b bg-card/60">
        <div className="mx-auto flex min-h-12 max-w-7xl flex-wrap items-center gap-2 px-3 py-2 sm:px-6">
          <h1 className="min-w-0 flex-1 truncate text-sm font-medium">{text.title}</h1>
          <LanguageToggle
            value={viewLang}
            hasEnglish={hasEnglishTree}
            onChange={setCurrentLang}
          />
        </div>
      </div>

      <main className="shrink-0 px-2 py-2 sm:px-4 sm:pt-3">
        <div className="h-[calc(100dvh-168px)] min-h-[320px]">
          {activeTree.nodes.length === 0 ? (
            <div className="flex h-full min-h-[360px] items-center justify-center rounded-lg border bg-card/40 p-6 text-center text-sm text-muted-foreground">
              {text.emptyTree}
            </div>
          ) : (
            <ReactFlowProvider>
              <OrgChart
                key={`${viewLang}-${activeTree.nodes.length}-${activeTree.edges.length}`}
                rawNodes={activeTree.nodes}
                rawEdges={activeTree.edges}
                hideToolbar
                compact
                showMiniMap
                onNodeClick={setSelected}
              />
            </ReactFlowProvider>
          )}
        </div>
      </main>

      <EmployeeDetailDrawer
        node={selected}
        mode="public"
        onClose={() => setSelected(null)}
      />

      <ShareWatermark payload={data?.watermark} />

      <footer className="shrink-0 border-t bg-card px-3 py-2 pb-[calc(0.5rem+env(safe-area-inset-bottom))] text-[11px] text-muted-foreground sm:px-6 sm:text-xs">
        <div className="mx-auto flex max-w-7xl flex-col gap-1 sm:flex-row sm:items-center sm:justify-between sm:gap-2">
          <span>{text.restricted}</span>
          {data?.generated_at && (
            <span>{text.generated} {new Date(data.generated_at).toLocaleString(viewLang)}</span>
          )}
        </div>
      </footer>
    </div>
  );
};

export default PublicOrgView;
