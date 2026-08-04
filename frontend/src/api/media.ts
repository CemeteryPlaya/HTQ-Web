import api from './client';
import { API_ENDPOINTS } from './endpoints';

const MEDIA_FILES = `${API_ENDPOINTS.mediaFiles}/`;

export const mediaApi = {
  upload: (file: File, isPublic = false) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('is_public', String(isPublic));
    return api.post(MEDIA_FILES, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
  download: (fileId: string) => api.get(`${MEDIA_FILES}${fileId}`, { responseType: 'blob' }),
  // Удаления файла в API нет: apps.media_files отдаёт на /files/{id} только
  // GET (405 на DELETE). Прежний метод `delete` никто не звал и звать было
  // нечего — удалён, чтобы не выглядел рабочим.
};
