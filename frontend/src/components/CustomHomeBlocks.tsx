/**
 * CustomHomeBlocks — все блоки, созданные редактором, в заданном им порядке.
 *
 * Отделено от `CustomHomeBlock` (который рисует ОДИН блок), чтобы `Index.tsx`
 * не знал ни про запрос, ни про фильтрацию системных секций: он просто ставит
 * компонент в нужное место ленты.
 *
 * Системные секции сюда не попадают — у них свои React-компоненты, и рисовать
 * их вторично generic-макетом означало бы дубль на странице.
 */
import { useHomeContent } from '@/hooks/useHomeContent';
import { CustomHomeBlock } from '@/components/CustomHomeBlock';

export function CustomHomeBlocks() {
  const { byKey } = useHomeContent();

  const custom = [...byKey.values()].filter((s) => !s.is_system);
  if (custom.length === 0) return null;

  return (
    <>
      {custom.map((section) => (
        <CustomHomeBlock key={section.id} section={section} />
      ))}
    </>
  );
}

export default CustomHomeBlocks;
