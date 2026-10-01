/**
 * Строка над формой счёта или договора о связи с альтернативой (B5.1,
 * D-B51-3): у нового документа — «Основание: альтернатива АП-…», у
 * исходного — чем он заменён (альтернатива и новый документ, ссылками).
 */
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Shuffle } from 'lucide-react';

import { documentUrl, offerUrl, type AlternativeLinks } from './links';

export function AlternativeLinksNote({ links }: { links?: AlternativeLinks | null }) {
  const { t } = useTranslation();
  if (!links || (!links.basis && !links.replaced_by)) return null;
  const replaced = links.replaced_by;
  return (
    <div className="space-y-1 rounded-md border bg-muted/40 p-3 text-sm text-muted-foreground">
      {links.basis && (
        <p className="flex items-start gap-2" data-testid="alternative-basis">
          <Shuffle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            {t('bpp.selection.basis', 'Основание: альтернатива')}{' '}
            <Link className="font-medium underline-offset-2 hover:underline"
                  to={offerUrl(links.basis.offer_id)}>
              {links.basis.offer_number}
            </Link>
          </span>
        </p>
      )}
      {replaced && (
        <p className="flex items-start gap-2" data-testid="alternative-replaced">
          <Shuffle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            {t('bpp.selection.replacedBy', 'Заменён альтернативой')}{' '}
            <Link className="font-medium underline-offset-2 hover:underline"
                  to={offerUrl(replaced.offer_id)}>
              {replaced.offer_number}
            </Link>
            {replaced.result_type && replaced.result_id && (
              <>
                {', '}{t('bpp.selection.newDocument', 'новый документ')}{' '}
                <Link className="font-medium underline-offset-2 hover:underline"
                      to={documentUrl(replaced.result_type, replaced.result_id)}>
                  {replaced.result_number}
                </Link>
              </>
            )}
          </span>
        </p>
      )}
    </div>
  );
}
