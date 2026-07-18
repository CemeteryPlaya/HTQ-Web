/** Domain types for the Requests microservice. Mirror the FastAPI DTOs. */

export type RequestStatus =
  | 'draft' | 'pending' | 'approved' | 'rejected' | 'cancelled' | 'returned';

export type ProjectStatus = 'active' | 'completed' | 'archived';
export type ProjectMemberRole = 'admin' | 'member' | 'viewer';

export interface Project {
  id: number;
  name: string;
  description: string;
  status: ProjectStatus;
  color: string;
  budget_limit: string | number | null;
  currency: string;
  start_date: string | null;
  end_date: string | null;
  owner_id: number | null;
  department_id: number | null;
  created_at: string;
  updated_at: string;
}

export interface ProjectMember {
  project_id: number;
  user_id: number;
  role: ProjectMemberRole;
  granted_by: number | null;
  granted_at: string;
}

/** Form field types — discriminated union mirroring `app/services/form_schema.py`. */
export type FormFieldType =
  | 'text' | 'number' | 'money' | 'amount' | 'date' | 'dropdown' | 'checkbox'
  | 'user_ref' | 'project_ref' | 'department_ref'
  | 'file' | 'table' | 'signature' | 'formula'
  | 'paragraph' | 'static_text' | 'serial' | 'reference' | 'group' | 'link_ref';

export interface FormFieldBase {
  key: string;
  label: string;
  required?: boolean;
  type: FormFieldType;
}

export interface MoneyField extends FormFieldBase {
  type: 'money';
  currency?: string;
  contributes_to_total?: boolean;
}

export interface NumberField extends FormFieldBase {
  type: 'number';
  min?: number;
  max?: number;
  contributes_to_total?: boolean;
}

export interface TextField extends FormFieldBase {
  type: 'text';
  max?: number;
}

export interface DropdownField extends FormFieldBase {
  type: 'dropdown';
  options: string[];
  multiple?: boolean;
}

export interface FormulaField extends FormFieldBase {
  type: 'formula';
  expr: string;
  contributes_to_total?: boolean;
}

/* ─── schema v2 (Lark parity) widgets ─────────────────────────────────── */

export interface AmountField extends FormFieldBase {
  type: 'amount';
  currencies?: string[];
  decimals?: number;
  amount_in_words?: boolean;
  thousand_separator?: boolean;
  contributes_to_total?: boolean;
}
export interface ParagraphField extends FormFieldBase { type: 'paragraph'; max?: number; }
export interface StaticTextField extends FormFieldBase { type: 'static_text'; content: string; }
export interface SerialField extends FormFieldBase { type: 'serial'; prefix?: string; }
export interface ReferenceField extends FormFieldBase {
  type: 'reference';
  source: string;
  column: string;
  depends_on?: string;
  multiple?: boolean;
}
export interface LinkRefField extends FormFieldBase {
  type: 'link_ref';
  template_slug?: string;
  multiple?: boolean;
}
export interface GroupField extends FormFieldBase {
  type: 'group';
  fields: FormField[];
  repeatable?: boolean;
  summarize_keys?: string[];
}

export type FormField =
  | MoneyField | NumberField | TextField | DropdownField | FormulaField
  | AmountField | ParagraphField | StaticTextField | SerialField
  | ReferenceField | LinkRefField | GroupField
  | (FormFieldBase & {
      type: Exclude<
        FormFieldType,
        'money' | 'number' | 'text' | 'dropdown' | 'formula'
        | 'amount' | 'paragraph' | 'static_text' | 'serial'
        | 'reference' | 'link_ref' | 'group'
      >;
    });

export interface DisplayCondition {
  target: string;
  match?: 'all' | 'any';
  conditions: { field: string; op?: string; value?: unknown }[];
}

export interface FormSchema {
  fields: FormField[];
  display_conditions?: DisplayCondition[];
}

export type WorkflowNodeType =
  | 'start' | 'approval' | 'condition' | 'notify' | 'acknowledge' | 'parallel'
  | 'end_approved' | 'end_rejected';

/** How a node's approver / CC is resolved (mirrors Lark's approver radio grid). */
export type AssigneeKind =
  | 'user' | 'users' | 'role' | 'initiator' | 'initiator_supervisor'
  | 'department_head' | 'project_admins' | 'field_ref';

export interface Assignee {
  kind: AssigneeKind;
  id?: number;
  ids?: number[];
  name?: string;
  field?: string;
  [k: string]: unknown;
}

export interface WorkflowNode {
  id: string;
  type: WorkflowNodeType;
  name?: string;
  assignee?: Assignee | null;
  mode?: 'any' | 'all' | 'sequential';
  expr?: Record<string, unknown> | null;
  cc?: Assignee[] | null;
  // Builder UI extras — round-tripped through workflow_json (the backend
  // validator ignores unknown node fields, so these persist untouched).
  approval_type?: 'manual' | 'auto_approve' | 'auto_reject';
  submit_scope?: 'all' | 'selected' | 'none';
  submit_user_ids?: number[];
  empty_rule?: 'auto_approve' | 'specify' | 'transfer_admin';
  same_person_rule?: 'review' | 'auto_skip' | 'forward_manager' | 'forward_department';
}

export interface WorkflowEdge {
  from: string;
  to: string;
  on?: 'approve' | 'reject';
  when?: 'true' | 'false';
}

export interface WorkflowGraph {
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
}

/** Advanced settings (Lark builder step 4 "More", screenshot 13). */
export interface TemplateSettings {
  // Submitter permissions
  allow_revoke_pending?: boolean;
  allow_revoke_within_days?: boolean;
  revoke_within_days?: number;
  allow_modify_approved?: boolean;
  modify_within_days?: number;
  allow_delegate_submission?: boolean;
  // Approver settings
  allow_batch?: boolean;
  allow_recall_decision?: boolean;
  show_instant_approval?: boolean;
  quick_approval_on_cards?: boolean;
  // Approver deduplication
  dedup?: 'once_auto' | 'consecutive_auto' | 'none';
  // Notifications / print
  notification_mode?: 'default' | 'custom';
  print_mode?: 'default' | 'custom';
  // Transfer / efficiency
  only_related_can_forward?: boolean;
  exclude_efficiency?: boolean;
}

/** Basic Info config (Lark builder step 1), stored in template.config_json. */
export interface TemplateConfig {
  group?: string;
  who_can_submit?: 'all' | 'selected' | 'none';
  submit_user_ids?: number[];
  show_on_workplace?: boolean;
  prohibit_admin_manage?: boolean;
  process_admin_ids?: number[];
  settings?: TemplateSettings;
}

export interface FormTemplate {
  id: number;
  project_id: number | null;
  name: string;
  slug: string;
  description: string;
  icon: string;
  color: string;
  config_json?: TemplateConfig;
  is_active: boolean;
  status?: 'active' | 'inactive' | 'deleted';
  created_by: number | null;
  current_version_id: number | null;
  created_at: string;
  updated_at: string;
}

export interface FormTemplateVersion {
  id: number;
  template_id: number;
  version: number;
  schema_json: FormSchema;
  workflow_json: WorkflowGraph;
  published_at: string;
  published_by: number | null;
}

export interface RequestInstance {
  id: number;
  code: string;
  template_id: number;
  template_version_id: number;
  project_id: number | null;
  initiator_id: number;
  title: string;
  status: RequestStatus;
  current_node_id: string | null;
  form_values_json: Record<string, unknown>;
  total_amount: string | number | null;
  currency: string | null;
  submitted_at: string | null;
  finalized_at: string | null;
  requires_admin_attention: boolean;
  created_at: string;
  updated_at: string;
}

export interface StatsOverview {
  from: string;
  to: string;
  by_status: Record<RequestStatus, { count: number; sum_amount: number }>;
}

/** Reference data source (Lark-Base-style lookup table). When `template_id` is
 *  set, it's a template's auto-maintained data table (Управление данными). */
export interface ReferenceSource {
  id: number;
  slug: string;
  name: string;
  columns: string[];
  template_id?: number | null;
  created_at: string;
  updated_at: string;
}
export interface ReferenceRow {
  id: number;
  source_id: number;
  data: Record<string, unknown>;
}
export interface ReferenceOptions {
  slug: string;
  column: string;
  options: string[];
}

/** A template's auto-maintained data table with the caller's access flags. */
export interface DataTable {
  id: number;
  slug: string;
  name: string;
  columns: string[];
  template_id: number | null;
  access_ids: number[];
  can_manage: boolean;
}
