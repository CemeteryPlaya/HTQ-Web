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
  delete: (fileId: string) => api.delete(`${MEDIA_FILES}${fileId}`),
};
