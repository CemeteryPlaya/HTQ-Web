import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';

import {
  depthFor,
  type DepthFlag,
  type DepthMap,
  type DepthPreset,
} from '@/lib/auth/permissions';
import type {
  AccessFunctionNode,
  AccessFunctionsResponse,
  AccessPageNode,
  RolePermission,
} from '@/types/access';

/**
 * Матрица прав роли: дерево функций × глубина.
 *
 * Два показателя, как их сформулировал заказчик. **Функция** — узел реестра:
 * модуль, экран внутри него или отдельное поле. **Глубина** — что с этой
 * функцией разрешено делать.
 *
 * Ключевое различие в интерфейсе — между «наследует» и «нет доступа», и оно не
 * косметическое:
 *
 * * **наследует** — строки нет вовсе, узел берёт глубину ближайшего предка.
 *   Так выглядит подавляющее большинство узлов: роль задаёт глубину на модуле,
 *   и всё внутри работает по ней.
 * * **нет доступа** — явный запрет, перекрывающий разрешение предка. Им
 *   закрывают зарплату внутри разрешённых кадров.
 *
 * Слить их в одно значило бы либо лишить возможности закрыть одно поле внутри
 * открытого модуля, либо заставить расписывать каждый узел вручную — то есть
 * получить матрицу на тысячу строк, которую никто не заполнит целиком.
 */

export interface RolePermissionMatrixProps {
  registry: AccessFunctionsResponse;
  value: RolePermission[];
  onChange: (next: RolePermission[]) => void;
  disabled?: boolean;
}

/** `''` — узел без собственной строки, то есть «наследует». */
type Choice = '' | DepthPreset;

/**
 * Узел-действие: единственный осмысленный признак — «доступно».
 *
 * Для него шесть уровней вырождаются в два, и показывать «видит» вместо
 * «разрешено» значит спрашивать не о том: у входа в конференцию нечего
 * «видеть», в него можно только войти или не войти.
 */
const isAction = (node: { flags: DepthFlag[] }): boolean =>
  node.flags.length === 1 && node.flags[0] === 'view';

const flatten = (nodes: AccessFunctionNode[], depth = 0): { node: AccessFunctionNode; depth: number }[] =>
  nodes.flatMap((node) => [
    { node, depth },
    ...flatten(node.children, depth + 1),
  ]);

export function RolePermissionMatrix({
  registry,
  value,
  onChange,
  disabled = false,
}: RolePermissionMatrixProps) {
  const { t } = useTranslation();

  const rows = useMemo(() => flatten(registry.tree), [registry.tree]);
  const explicit = useMemo(
    () => new Map(value.map((item) => [item.node, item])),
    [value],
  );
  /** Карта для расчёта унаследованного значения — та же форма, что у `/me`. */
  const asMap: DepthMap = useMemo(
    () => Object.fromEntries(value.map((item) => [item.node, item.flags])),
    [value],
  );
  const flagsOf = useMemo(
    () => new Map(registry.presets.map((p) => [p.key, p.flags])),
    [registry.presets],
  );

  const choose = (node: string, choice: Choice) => {
    const without = value.filter((item) => item.node !== node);
    if (choice === '') {
      onChange(without);
      return;
    }
    const flags = (flagsOf.get(choice) ?? []) as DepthFlag[];
    onChange([...without, { node, flags, preset: choice }]);
  };

  /** Что реально действует на узле, если своей строки у него нет. */
  const inheritedTitle = (path: string): string => {
    const parts = path.split('.');
    const parentPath = parts.slice(0, -1).join('.');
    const flags = parentPath ? depthFor(asMap, parentPath) : [];
    const preset = registry.presets.find(
      (p) => p.flags.length === flags.length && p.flags.every((f) => flags.includes(f)),
    );
    return preset ? preset.title : flags.join(', ') || t('access.matrix.noAccess', 'нет доступа');
  };

  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full text-sm">
        <thead className="bg-muted/50 text-xs text-muted-foreground">
          <tr>
            <th scope="col" className="px-3 py-2 text-left font-medium">
              {t('access.matrix.functionColumn', 'Функция')}
            </th>
            <th scope="col" className="w-64 px-3 py-2 text-left font-medium">
              {t('access.matrix.depthColumn', 'Глубина')}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ node, depth }) => {
            const own = explicit.get(node.path);
            const choice: Choice = own ? (own.preset ?? '') : '';
            const isModule = node.kind === 'module';
            return (
              <tr key={node.path} className="border-t">
                <th scope="row" className="px-3 py-1.5 text-left font-normal">
                  <span style={{ paddingLeft: `${depth * 18}px` }} className="inline-block">
                    <span className={isModule ? 'font-medium' : ''}>{node.title}</span>
                    <span className="ml-2 text-xs text-muted-foreground">{node.path}</span>
                  </span>
                </th>
                <td className="px-3 py-1.5">
                  <select
                    className="h-8 w-full rounded-md border bg-background px-2 text-sm"
                    value={choice}
                    disabled={disabled}
                    aria-label={`${node.title}: ${t('access.matrix.depthColumn', 'Глубина')}`}
                    onChange={(event) => choose(node.path, event.target.value as Choice)}
                  >
                    <option value="">
                      {isModule
                        ? t('access.matrix.notSet', 'не задано (нет доступа)')
                        : t('access.matrix.inherits', 'наследует: {{value}}',
                          { value: inheritedTitle(node.path) })}
                    </option>
                    {registry.presets
                      // Список допустимых уровней считает СЕРВЕР (реестр знает
                      // тип модуля и применимые признаки). Выводить его здесь
                      // заново значило бы завести второй ответ на тот же
                      // вопрос — и разойтись с валидацией на первом же модуле.
                      .filter((preset) => preset.key !== 'none'
                        && node.presets.includes(preset.key))
                      .map((preset) => (
                        <option key={preset.key} value={preset.key}>
                          {isAction(node) && preset.key === 'view'
                            ? t('access.matrix.allowed', 'разрешено')
                            : preset.title}
                        </option>
                      ))}
                    <option value="none">
                      {t('access.matrix.noAccess', 'нет доступа')}
                    </option>
                  </select>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {registry.pages.length > 0 && (
        <PageSection
          pages={registry.pages}
          explicit={explicit}
          disabled={disabled}
          onChoose={choose}
        />
      )}
    </div>
  );
}

/**
 * Страницы — слой выше остальных.
 *
 * Не видя страницы, человек не сделает на ней ничего, какие бы глубины ему ни
 * выдали. Но это ВЕТО, а не разрешение: страница без запрета работает по
 * обычным правилам, поэтому вариант по умолчанию — «не ограничена», а не
 * «закрыта». Иначе всякая роль, где страницы не перечислены поимённо,
 * оказалась бы бесполезной, а перечень пришлось бы обновлять при каждом новом
 * экране.
 */
function PageSection({
  pages,
  explicit,
  disabled,
  onChoose,
}: {
  pages: AccessPageNode[];
  explicit: Map<string, RolePermission>;
  disabled: boolean;
  onChoose: (node: string, choice: Choice) => void;
}) {
  const { t } = useTranslation();

  return (
    <div className="border-t">
      <div className="bg-muted/50 px-3 py-2 text-xs font-medium text-muted-foreground">
        {t('access.matrix.pages', 'Страницы сайта')}
        <span className="ml-2 font-normal">
          {t('access.matrix.pagesHint',
            'закрытая страница отменяет всё, что разрешено выше')}
        </span>
      </div>
      <table className="w-full text-sm">
        <tbody>
          {pages.map((page) => {
            const choice: Choice = explicit.get(page.path)?.preset ?? '';
            return (
              <tr key={page.path} className="border-t">
                <th scope="row" className="px-3 py-1.5 text-left font-normal">
                  {page.title}
                  <span className="ml-2 text-xs text-muted-foreground">{page.route}</span>
                </th>
                <td className="w-64 px-3 py-1.5">
                  <select
                    className="h-8 w-full rounded-md border bg-background px-2 text-sm"
                    value={choice}
                    disabled={disabled}
                    aria-label={`${page.title}: ${t('access.matrix.pageAccess', 'Страница')}`}
                    onChange={(event) => onChoose(page.path, event.target.value as Choice)}
                  >
                    <option value="">
                      {t('access.matrix.pageUnrestricted', 'не ограничена')}
                    </option>
                    <option value="view">{t('access.matrix.pageVisible', 'видна')}</option>
                    <option value="none">{t('access.matrix.pageHidden', 'скрыта')}</option>
                  </select>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default RolePermissionMatrix;
