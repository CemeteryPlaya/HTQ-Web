/* Types for department folder / file manager */

export interface DepartmentFolder {
  id: number;
  department: number;
  department_name: string;
  files_count: number;
  created_at: string;
}

export interface DepartmentFileFolder {
  id: number;
  department: number;
  name: string;
  files_count: number;
  created_by: number | null;
  created_by_name: string | null;
  created_at: string;
}

export interface DepartmentFile {
  id: number;
  folder: number;
  file_folder: number | null;
  name: string;
  file: string;
  file_url: string;
  file_size: number;
  uploaded_by: number | null;
  uploaded_by_name: string | null;
  description: string;
  created_at: string;
}
