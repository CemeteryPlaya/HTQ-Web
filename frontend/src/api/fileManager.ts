/* ------------------------------------------------------------------ */
/*  Department File Manager — API helpers                              */
/* ------------------------------------------------------------------ */
import api from '@/api/client';
import { API_ENDPOINTS } from '@/api/endpoints';
import type { DepartmentFolder, DepartmentFile, DepartmentFileFolder } from '@/types/fileManager';

const HR = `${API_ENDPOINTS.hr}/`;

/* Unwrap paginated or plain array response */
function unwrap<T>(data: any): T[] {
  if (Array.isArray(data)) return data;
  if (Array.isArray(data?.results)) return data.results;
  return [];
}

/* ---------- Folders ---------- */
export const fetchMyFolders = async (): Promise<DepartmentFolder[]> => {
  const res = await api.get(`${HR}department-folders/`);
  return unwrap<DepartmentFolder>(res.data);
};

export const fetchFolder = async (id: number): Promise<DepartmentFolder> => {
  const res = await api.get(`${HR}department-folders/${id}/`);
  return res.data;
};

export const fetchDepartmentFileFolders = async (
  departmentId: number,
): Promise<DepartmentFileFolder[]> => {
  const res = await api.get(`${HR}department-file-folders/`, {
    params: { department: departmentId },
  });
  return unwrap<DepartmentFileFolder>(res.data);
};

export const createDepartmentFileFolder = async (
  departmentId: number,
  name: string,
): Promise<DepartmentFileFolder> => {
  const res = await api.post(`${HR}department-file-folders/`, {
    department: departmentId,
    name,
  });
  return res.data;
};

/* ---------- Files ---------- */
export const fetchFolderFiles = async (
  folderId: number,
  options: { fileFolderId?: number | null; rootOnly?: boolean } = {},
): Promise<DepartmentFile[]> => {
  const res = await api.get(`${HR}department-files/`, {
    params: {
      folder: folderId,
      file_folder: options.fileFolderId ?? undefined,
      root_only: options.rootOnly || undefined,
    },
  });
  return unwrap<DepartmentFile>(res.data);
};

export const uploadFile = async (
  folderId: number,
  file: File,
  description?: string,
  fileFolderId?: number | null,
): Promise<DepartmentFile> => {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('folder', String(folderId));
  formData.append('name', file.name);
  if (fileFolderId != null) formData.append('file_folder', String(fileFolderId));
  if (description) formData.append('description', description);

  const res = await api.post(`${HR}department-files/`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return res.data;
};

export const deleteFile = async (fileId: number): Promise<void> => {
  await api.delete(`${HR}department-files/${fileId}/`);
};

/* ---------- Cross-department search ---------- */
export const searchFiles = async (
  q: string,
  limit = 20,
): Promise<DepartmentFile[]> => {
  const query = new URLSearchParams({ q, limit: String(limit) }).toString();
  const res = await api.get(`${HR}department-files/search/?${query}`);
  return unwrap<DepartmentFile>(res.data);
};

/* ---------- Download helper ---------- */
export const downloadFileUrl = (fileUrl: string): void => {
  const a = document.createElement('a');
  a.href = fileUrl;
  a.download = '';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
};
