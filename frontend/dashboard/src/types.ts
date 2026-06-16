export type SortOrder = "asc" | "desc";
export type BuiltinView = "sessions" | "proactive" | "chat";
export type ViewMode = BuiltinView | `plugin:${string}`;

export interface PageResult<T> {
  items: T[];
  total: number;
  page?: number;
  page_size?: number;
}

export interface SessionRow {
  key: string;
  created_at: string;
  updated_at: string;
  last_consolidated: number;
  metadata: Record<string, unknown>;
  last_user_at: string | null;
  last_proactive_at: string | null;
  message_count: number;
}

export interface MessageRow {
  id: string;
  session_key: string;
  seq: number;
  role: string;
  content: string;
  tool_chain: unknown;
  extra: Record<string, unknown>;
  ts: string;
}

export interface ChatStatus {
  enabled: boolean;
  reason: string;
  default_session_key: string;
  streaming: boolean;
  session_key?: string;
  latest_seq?: number;
  active?: boolean;
  replay_limit?: number;
}

export interface ChatCommandManifest {
  schema_version: string;
  enabled?: boolean;
  reason?: string;
  commands: ChatCommandPack[];
}

export interface ChatCommandPack {
  prefix: string;
  plugin_id: string;
  display_name: string;
  description: string;
  examples: string[];
  options: Record<string, unknown>;
  workflows: ChatCommandWorkflow[];
  templates?: Record<string, unknown>[];
  status?: BiomedCommandStatus;
}

export interface ChatCommandWorkflow {
  name: string;
  label: string;
  tool_name?: string;
  contract?: Record<string, unknown>;
  risk_level?: string;
  requires_confirmation?: boolean;
}

export interface BiomedCommandStatus {
  command: string;
  llm_provider: {
    status: "configured" | "missing" | string;
    model?: string;
    missing_effect?: string;
    features?: Record<string, boolean>;
  };
  pubmed: {
    status: "enabled" | "disabled" | "unreachable" | "unchecked" | string;
    policy_status?: "enabled" | "disabled" | string;
    network_status?: "enabled" | "disabled" | "unreachable" | "unchecked" | string;
    allow_live_pubmed_tools?: boolean;
    message?: string;
  };
  source: {
    default_source: string;
    live_pubmed_opt_in?: boolean;
  };
  limits: Record<string, number>;
  exports: Record<string, boolean>;
  confirmation: {
    required_for: string[];
  };
  config_path?: string;
}

export interface ChatCommandRequirement {
  kind: string;
  label: string;
  detail: string;
}

export interface ChatCommandPreview {
  session_key: string;
  kind: "biomed" | "message" | string;
  ok: boolean;
  command: string;
  action: string;
  tool_name?: string;
  arguments: Record<string, unknown>;
  flags?: Record<string, unknown>;
  missing_requirements: ChatCommandRequirement[];
  confirmation?: Record<string, unknown> | null;
  final_prompt: string;
  can_send: boolean;
  errors: string[];
  readiness?: BiomedCommandStatus;
  artifacts?: ChatRunArtifacts | null;
}

export interface ChatRunArtifacts {
  run_id?: string;
  watch_id?: string;
  review_url?: string;
  packet_url?: string;
  trace_url?: string;
  provenance_url?: string;
  [key: string]: unknown;
}

export interface ChatSessionMetadata {
  title?: string;
  title_source?: string;
  created_from?: string;
  [key: string]: unknown;
}

export interface ChatEventRow {
  id: string;
  session_key: string;
  event: string;
  kind: string;
  label: string;
  seq?: number;
  role?: string;
  content?: string;
  detail?: string;
  content_delta?: string;
  thinking_delta?: string;
  thinking?: string;
  tool_name?: string;
  call_id?: string;
  arguments?: unknown;
  final_arguments?: unknown;
  approval_id?: string;
  confirmation?: unknown;
  status?: string;
  iteration?: number;
  has_more?: boolean;
  final?: boolean;
  summary?: string;
  technical_detail?: string;
  raw?: unknown;
  metadata?: Record<string, unknown>;
  source?: "history" | "live" | "local";
  pending?: boolean;
  ts?: string;
  created_at: string;
}

export interface ChatTurn {
  session_key: string;
  user?: ChatEventRow | null;
  assistant?: ChatEventRow | null;
  thinking?: ChatThinkingState | null;
  approval?: ChatEventRow | null;
  actionTarget?: "review" | "packet" | "provenance" | "trace";
  error?: ChatEventRow | null;
  warning?: ChatEventRow | null;
}

export interface ChatThinkingState {
  status: "idle" | "running" | "done" | "error";
  summary: string;
  steps: string[];
  technicalDetail?: string;
  startedAt?: string;
  updatedAt?: string;
  expanded?: boolean;
}

export interface ProactiveOverview {
  counts: Record<string, number>;
  result_counts: Record<string, number>;
  flow_counts: Record<string, number>;
  last_tick_at: string | null;
  last_send_at: string | null;
  last_skip_reason: string | null;
  recent_tick: ProactiveTick | null;
}

export interface ProactiveTick {
  tick_id: string;
  session_key: string;
  started_at: string;
  finished_at?: string | null;
  gate_exit?: string | null;
  terminal_action?: string | null;
  skip_reason?: string | null;
  steps_taken?: number;
  drift_entered?: boolean | number;
  final_message?: string | null;
  alert_count?: number;
  content_count?: number;
  context_count?: number;
  interesting_ids?: string[];
  discarded_ids?: string[];
  cited_ids?: string[];
}

export interface ProactiveStep {
  step_index: number;
  phase: string;
  tool_name: string;
  tool_call_id: string;
  tool_args: unknown;
  tool_result_text: string;
  terminal_action_after: string;
  skip_reason_after: string;
  final_message_after: string;
  interesting_ids_after: string[];
  discarded_ids_after: string[];
  cited_ids_after: string[];
}

export interface DashboardColumn {
  key: string;
  label: string;
  width?: number;
  flex?: boolean;
  fmt?: string;
  align?: "left" | "right";
  cellClass?: string;
  rawTitle?: boolean;
  sortable?: boolean;
  renderCell?(value: unknown, item: Record<string, unknown>): string;
}

export interface FetchPageOpts {
  page: number;
  pageSize: number;
  filters?: Record<string, string>;
  sortBy?: string;
  sortOrder?: SortOrder;
}

export interface FetchPageResult {
  items: Record<string, unknown>[];
  total: number;
}

// Dispatch context passed to all plugin render slots
export interface PluginDispatch {
  readonly filters: Readonly<Record<string, string>>;
  setFilter(key: string, value: string): void;
  clearFilter(key: string): void;
  setFilters(next: Record<string, string>): void;
  clearFilters(keys: string[]): void;
  readonly sortBy: string;
  readonly sortOrder: SortOrder;
  setSort(key: string): void;
  refresh(): void;
  activate(): void;
}

export interface PluginBatchAction {
  label: string;
  className: string;
  run(ids: string[]): Promise<void>;
}

export type PluginLayout = "table" | "workbench";

export interface PluginConfig {
  id: string;
  label: string;
  viewLabel?: string;
  layout?: PluginLayout;
  pageSize?: number;
  countTitle?: (n: number) => string;
  rowKey: string;
  columns: DashboardColumn[];
  defaultSortBy?: string;
  defaultSortOrder?: SortOrder;
  getCount(): Promise<number | null>;
  fetchPage(opts: FetchPageOpts): Promise<FetchPageResult>;
  fetchDetail?: (item: Record<string, unknown>) => Promise<Record<string, unknown>>;
  rowClass?: (item: Record<string, unknown>) => string;
  emptyMessage?: string;
  renderMain?(container: HTMLElement, dispatch: PluginDispatch): void;
  renderDetail?(item: Record<string, unknown> | null, container: HTMLElement, dispatch?: PluginDispatch): void;
  renderNavBody?(container: HTMLElement, dispatch: PluginDispatch): void;
  renderFilters?(container: HTMLElement, dispatch: PluginDispatch): void;
  renderTopbarAction?(container: HTMLElement, dispatch: PluginDispatch): void;
  batchActions?: PluginBatchAction[];
  formatters?: Record<string, (value: unknown, item: Record<string, unknown>) => string>;
}

export interface PluginState {
  page: number;
  pageSize: number;
  total: number;
  items: Record<string, unknown>[];
  activeRowKey: string | null;
  activeDetail: Record<string, unknown> | null;
  filters: Record<string, string>;
  sortBy: string;
  sortOrder: SortOrder;
  selectedIds: Set<string>;
}

export interface DashboardGlobal {
  _plugins: PluginConfig[];
  _formatters: Record<string, (value: unknown, item: Record<string, unknown>) => string>;
  registerPlugin(config: PluginConfig): void;
  registerFormatter(name: string, fn: (value: unknown, item: Record<string, unknown>) => string): void;
}
