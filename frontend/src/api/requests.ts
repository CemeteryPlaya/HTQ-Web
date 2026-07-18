/* Requests microservice — typed HTTP client. Mirrors services/requests/app/api/v1. */

import api from '@/api/client';
import { API_ENDPOINTS } from '@/api/endpoints';
import type {
  DataTable, FormTemplate, FormTemplateVersion, Project, ProjectMember, RequestInstance,
  ReferenceOptions, ReferenceRow, ReferenceSource, StatsOverview,
} from '@/features/requests/types';

const BASE = `${API_ENDPOINTS.requests}/`;

function unwrap<T>(data: unknown): T[] {
  if (Array.isArray(data)) return data as T[];
  if (data && typeof data === 'object' && Array.isArray((data as any).results)) {
    return (data as any).results as T[];
  }
  return [];
}

export const requestsApi = {
  /* ─── projects ──────────────────────────────────────────────────────── */
  projects: {
    async list(): Promise<Project[]> {
      const { data } = await api.get(`${BASE}projects/`);
      return unwrap<Project>(data);
    },
    async get(id: number): Promise<Project> {
      const { data } = await api.get(`${BASE}projects/${id}/`);
      return data;
    },
    async create(payload: Partial<Project> & { name: string }): Promise<Project> {
      const { data } = await api.post(`${BASE}projects/`, payload);
      return data;
    },
    async update(id: number, payload: Partial<Project>): Promise<Project> {
      const { data } = await api.patch(`${BASE}projects/${id}/`, payload);
      return data;
    },
    async remove(id: number): Promise<void> {
      await api.delete(`${BASE}projects/${id}/`);
    },
    async listMembers(id: number): Promise<ProjectMember[]> {
      const { data } = await api.get(`${BASE}projects/${id}/members/`);
      return unwrap<ProjectMember>(data);
    },
    async addMember(id: number, user_id: number, role: 'admin' | 'member' | 'viewer'): Promise<ProjectMember> {
      const { data } = await api.post(`${BASE}projects/${id}/members/`, { user_id, role });
      return data;
    },
    async removeMember(id: number, user_id: number): Promise<void> {
      await api.delete(`${BASE}projects/${id}/members/${user_id}/`);
    },
  },

  /* ─── templates ─────────────────────────────────────────────────────── */
  templates: {
    async list(project_id?: number | null): Promise<FormTemplate[]> {
      const params = project_id != null ? { project_id } : undefined;
      const { data } = await api.get(`${BASE}templates/`, { params });
      return unwrap<FormTemplate>(data);
    },
    async get(id: number): Promise<FormTemplate> {
      const { data } = await api.get(`${BASE}templates/${id}/`);
      return data;
    },
    async create(payload: Partial<FormTemplate> & { name: string }): Promise<FormTemplate> {
      const { data } = await api.post(`${BASE}templates/`, payload);
      return data;
    },
    async update(id: number, payload: Partial<FormTemplate>): Promise<FormTemplate> {
      const { data } = await api.patch(`${BASE}templates/${id}/`, payload);
      return data;
    },
    async deactivate(id: number): Promise<FormTemplate> {
      const { data } = await api.post(`${BASE}templates/${id}/deactivate/`);
      return data;
    },
    async activate(id: number): Promise<FormTemplate> {
      const { data } = await api.post(`${BASE}templates/${id}/activate/`);
      return data;
    },
    async remove(id: number): Promise<void> {
      await api.delete(`${BASE}templates/${id}/`);
    },
    async getVersion(template_id: number, version_id: number): Promise<FormTemplateVersion> {
      const { data } = await api.get(`${BASE}templates/${template_id}/versions/${version_id}/`);
      return data;
    },
    async publishVersion(template_id: number, schema_json: unknown, workflow_json: unknown): Promise<FormTemplateVersion> {
      const { data } = await api.post(`${BASE}templates/${template_id}/versions/`, {
        schema_json, workflow_json,
      });
      return data;
    },
    async preview(schema_json: unknown, workflow_json: unknown) {
      const { data } = await api.post(`${BASE}templates/preview/`, { schema_json, workflow_json });
      return data;
    },
  },

  /* ─── instances ─────────────────────────────────────────────────────── */
  instances: {
    async list(box: 'inbox' | 'sent' | 'cc' | 'done' = 'inbox'): Promise<RequestInstance[]> {
      const { data } = await api.get(`${BASE}instances/`, { params: { box } });
      return unwrap<RequestInstance>(data);
    },
    async get(id: number): Promise<RequestInstance> {
      const { data } = await api.get(`${BASE}instances/${id}/`);
      return data;
    },
    async create(payload: {
      template_id: number; title?: string; project_id?: number | null;
      form_values?: Record<string, unknown>;
    }): Promise<RequestInstance> {
      const { data } = await api.post(`${BASE}instances/`, payload);
      return data;
    },
    async update(id: number, payload: { title?: string; form_values?: Record<string, unknown> }): Promise<RequestInstance> {
      const { data } = await api.patch(`${BASE}instances/${id}/`, payload);
      return data;
    },
    async submit(id: number): Promise<RequestInstance> {
      const { data } = await api.post(`${BASE}instances/${id}/submit/`);
      return data;
    },
    async resubmit(id: number): Promise<RequestInstance> {
      const { data } = await api.post(`${BASE}instances/${id}/resubmit/`);
      return data;
    },
  },

  /* ─── actions ───────────────────────────────────────────────────────── */
  actions: {
    async approve(id: number, comment = ''): Promise<RequestInstance> {
      const { data } = await api.post(`${BASE}instances/${id}/approve/`, { comment });
      return data;
    },
    async reject(id: number, comment = ''): Promise<RequestInstance> {
      const { data } = await api.post(`${BASE}instances/${id}/reject/`, { comment });
      return data;
    },
    async requestChanges(id: number, comment = ''): Promise<RequestInstance> {
      const { data } = await api.post(`${BASE}instances/${id}/request-changes/`, { comment });
      return data;
    },
    async cancel(id: number): Promise<RequestInstance> {
      const { data } = await api.post(`${BASE}instances/${id}/cancel/`, { comment: '' });
      return data;
    },
  },

  /* ─── stats ─────────────────────────────────────────────────────────── */
  stats: {
    async overview(from?: string, to?: string): Promise<StatsOverview> {
      const { data } = await api.get(`${BASE}stats/overview`, { params: { from, to } });
      return data;
    },
    async byProject(project_id: number) {
      const { data } = await api.get(`${BASE}stats/by-project`, { params: { project_id } });
      return data;
    },
    async byTemplate(params?: { from?: string; to?: string; project_id?: number }) {
      const { data } = await api.get(`${BASE}stats/by-template`, { params });
      return data;
    },
    async byActor(params: { role: 'initiator' | 'approver'; from?: string; to?: string; limit?: number }) {
      const { data } = await api.get(`${BASE}stats/by-actor`, { params });
      return data;
    },
    async heatmap(params?: { from?: string; to?: string }) {
      const { data } = await api.get(`${BASE}stats/heatmap`, { params });
      return data;
    },
  },

  /* ─── reference data sources (Lark Base) ────────────────────────────── */
  reference: {
    async list(): Promise<ReferenceSource[]> {
      const { data } = await api.get(`${BASE}reference-sources/`);
      return unwrap<ReferenceSource>(data);
    },
    async get(id: number): Promise<ReferenceSource> {
      const { data } = await api.get(`${BASE}reference-sources/${id}/`);
      return data;
    },
    async create(payload: { name: string; slug?: string; columns: string[] }): Promise<ReferenceSource> {
      const { data } = await api.post(`${BASE}reference-sources/`, payload);
      return data;
    },
    async update(id: number, payload: { name?: string; columns?: string[] }): Promise<ReferenceSource> {
      const { data } = await api.patch(`${BASE}reference-sources/${id}/`, payload);
      return data;
    },
    async remove(id: number): Promise<void> {
      await api.delete(`${BASE}reference-sources/${id}/`);
    },
    async listRows(id: number): Promise<ReferenceRow[]> {
      const { data } = await api.get(`${BASE}reference-sources/${id}/rows/`);
      return unwrap<ReferenceRow>(data);
    },
    async addRow(id: number, rowData: Record<string, unknown>): Promise<ReferenceRow> {
      const { data } = await api.post(`${BASE}reference-sources/${id}/rows/`, { data: rowData });
      return data;
    },
    async removeRow(id: number, rowId: number): Promise<void> {
      await api.delete(`${BASE}reference-sources/${id}/rows/${rowId}/`);
    },
    async options(slug: string, column: string, filterCol?: string, filterVal?: string): Promise<ReferenceOptions> {
      const { data } = await api.get(`${BASE}reference-sources/by-slug/${slug}/options`, {
        params: { column, filter_col: filterCol, filter_val: filterVal },
      });
      return data;
    },
    async myDataTables(): Promise<DataTable[]> {
      const { data } = await api.get(`${BASE}reference-sources/my-data-tables`);
      return unwrap<DataTable>(data);
    },
    async setAccess(id: number, viewer_ids: number[]): Promise<DataTable> {
      const { data } = await api.patch(`${BASE}reference-sources/${id}/access`, { viewer_ids });
      return data;
    },
  },
};
