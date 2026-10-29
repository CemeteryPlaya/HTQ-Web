/** Отказ 409 `E-CON-01` — карточку изменили после того, как её прочитали. */
import { errorCode } from '@/lib/apiError';

export const CONFLICT_CODE = 'E-CON-01';

export const isConflict = (error: unknown): boolean => errorCode(error) === CONFLICT_CODE;
