import React, { useCallback, useEffect, useEffectEvent, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { ChevronDown, Copy, ExternalLink, FileText, Info, LoaderCircle, Plus, Search, Trash2 } from "lucide-react";
import { api, asPageResult, pageCount } from "./api";
import {
  encodePath,
  formatSessionKeyForTable,
  proactiveFlowLabel,
  proactiveResultLabel,
  proactiveSectionLabel,
  proactiveTickPreview,
  relativeTime,
  renderMarkdown,
  roleClass,
  shortTs,
  stripMarkdown,
} from "./format";
import { attachJsonViewers, installDashboardGlobals, jvPlaceholder, loadPluginAssets } from "./pluginRuntime";
import { PluginDetail, PluginMain } from "./PluginDetail";
import type {
  DashboardColumn,
  ChatEventRow,
  ChatCommandManifest,
  ChatCommandPlanPreview,
  ChatCommandPreview,
  ChatRunArtifacts,
  ChatSessionMetadata,
  ChatStatus,
  ChatThinkingState,
  ChatTurn,
  MessageRow,
  PageResult,
  PluginBatchAction,
  PluginConfig,
  PluginDispatch,
  PluginState,
  ProactiveOverview,
  ProactiveStep,
  ProactiveTick,
  SessionRow,
  SortOrder,
  ViewMode,
} from "./types";

type NavOpen = Record<string, boolean>;

interface RunReviewDrawerState {
  runId: string;
  target: "review" | "packet" | "provenance" | "trace";
  loading: boolean;
  error: string | null;
  review: Record<string, unknown> | null;
  packet: Record<string, unknown> | null;
  trace: Record<string, unknown> | null;
  provenance: Record<string, unknown> | null;
}

// Creates a PluginDispatch bound to the given plugin + latest state getter.
function makeDispatch(
  plugin: PluginConfig,
  getState: () => PluginState | null,
  onSetState: (updater: (s: PluginState) => PluginState) => void,
  onActivate?: () => void,
): PluginDispatch {
  const fetchAndApply = async (
    nextFilters: Record<string, string>,
    nextSortBy: string,
    nextSortOrder: SortOrder,
  ): Promise<void> => {
    const state = getState();
    if (!state) return;
    const result = await plugin.fetchPage({ page: 1, pageSize: state.pageSize, filters: nextFilters, sortBy: nextSortBy, sortOrder: nextSortOrder });
    onSetState((s) => ({
      ...s,
      page: 1,
      total: result.total || 0,
      items: result.items || [],
      activeRowKey: null,
      activeDetail: null,
      filters: nextFilters,
      sortBy: nextSortBy,
      sortOrder: nextSortOrder,
    }));
  };

  const updateFilters = (updater: (filters: Record<string, string>) => Record<string, string>): void => {
    const state = getState();
    if (!state) return;
    void fetchAndApply(updater({ ...state.filters }), state.sortBy, state.sortOrder);
  };

  return {
    get filters() { return getState()?.filters ?? {}; },
    setFilter(key: string, value: string): void {
      updateFilters((filters) => ({ ...filters, [key]: value }));
    },
    clearFilter(key: string): void {
      updateFilters((filters) => {
        delete filters[key];
        return filters;
      });
    },
    setFilters(next: Record<string, string>): void {
      updateFilters((filters) => ({ ...filters, ...next }));
    },
    clearFilters(keys: string[]): void {
      updateFilters((filters) => {
        for (const key of keys) delete filters[key];
        return filters;
      });
    },
    get sortBy() { return getState()?.sortBy ?? ""; },
    get sortOrder() { return getState()?.sortOrder ?? "desc"; },
    setSort(key: string): void {
      const state = getState();
      if (!state) return;
      const nextOrder: SortOrder = state.sortBy === key && state.sortOrder === "desc" ? "asc" : "desc";
      void fetchAndApply(state.filters, key, nextOrder);
    },
    refresh(): void {
      const state = getState();
      if (!state) return;
      void fetchAndApply(state.filters, state.sortBy, state.sortOrder);
    },
    activate(): void {
      onActivate?.();
    },
  };
}

function App(): React.ReactElement {
  const [viewMode, setViewMode] = useState<ViewMode>("sessions");
  const [navOpen, setNavOpen] = useState<NavOpen>({ sessions: false, proactive: false });
  const [plugins, setPlugins] = useState<PluginConfig[]>([]);
  const [pluginState, setPluginState] = useState<Record<string, PluginState>>({});
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [sessionSearch, setSessionSearch] = useState("");
  const [sessionChannel, setSessionChannel] = useState("");
  const [activeSessionKey, setActiveSessionKey] = useState<string | null>(null);
  const [activeSession, setActiveSession] = useState<SessionRow | null>(null);
  const [messages, setMessages] = useState<MessageRow[]>([]);
  const [messageSearch, setMessageSearch] = useState("");
  const [messageRole, setMessageRole] = useState("");
  const [messagePage, setMessagePage] = useState(1);
  const [messageSortBy, setMessageSortBy] = useState("ts");
  const [messageSortOrder, setMessageSortOrder] = useState<SortOrder>("desc");
  const [totalMessages, setTotalMessages] = useState(0);
  const [activeMessage, setActiveMessage] = useState<MessageRow | null>(null);
  const [selectedMessageIds, setSelectedMessageIds] = useState<Set<string>>(new Set());
  const [proactiveOverview, setProactiveOverview] = useState<ProactiveOverview | null>(null);
  const [proactiveSection, setProactiveSection] = useState("all");
  const [proactiveItems, setProactiveItems] = useState<ProactiveTick[]>([]);
  const [proactivePage, setProactivePage] = useState(1);
  const [proactiveSortBy, setProactiveSortBy] = useState("started_at");
  const [proactiveSortOrder, setProactiveSortOrder] = useState<SortOrder>("desc");
  const [proactiveTotal, setProactiveTotal] = useState(0);
  const [proactiveSessionFilter, setProactiveSessionFilter] = useState("");
  const [activeProactiveKey, setActiveProactiveKey] = useState<string | null>(null);
  const [activeProactiveDetail, setActiveProactiveDetail] = useState<ProactiveTick | null>(null);
  const [activeProactiveSteps, setActiveProactiveSteps] = useState<ProactiveStep[]>([]);
  const [chatStatus, setChatStatus] = useState<ChatStatus | null>(null);
  const [chatSessionKey, setChatSessionKey] = useState("dashboard:default");
  const [chatInput, setChatInput] = useState("");
  const [chatEvents, setChatEvents] = useState<ChatEventRow[]>([]);
  const [chatSending, setChatSending] = useState(false);
  const [chatConnected, setChatConnected] = useState(false);
  const [chatLiveEvent, setChatLiveEvent] = useState<string>("");
  const [chatCommands, setChatCommands] = useState<ChatCommandManifest | null>(null);
  const [chatCommandPreview, setChatCommandPreview] = useState<ChatCommandPreview | null>(null);
  const [chatCommandPreviewKey, setChatCommandPreviewKey] = useState("");
  const [chatCommandPreviewLoading, setChatCommandPreviewLoading] = useState(false);
  const [chatDeleteTarget, setChatDeleteTarget] = useState<SessionRow | null>(null);
  const [chatReviewDrawer, setChatReviewDrawer] = useState<RunReviewDrawerState | null>(null);
  const [chatApprovalState, setChatApprovalState] = useState<Record<string, "approving" | "rejecting" | "approved" | "rejected" | "failed">>({});
  const [creatingChat, setCreatingChat] = useState(false);
  const [deletingChatKey, setDeletingChatKey] = useState<string | null>(null);
  const chatAbortRef = useRef<AbortController | null>(null);
  const chatStreamRef = useRef<ReadableStreamDefaultReader<Uint8Array> | null>(null);
  const chatSeqRef = useRef<Record<string, number>>({});
  const chatEventsRef = useRef<ChatEventRow[]>([]);
  const chatPreviewRef = useRef<Record<string, ChatCommandPreview | null>>({});
  const [hiddenPlugins, setHiddenPlugins] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);

  const messagePageSize = 25;
  const proactivePageSize = 25;
  const currentPluginId = viewMode.startsWith("plugin:") ? viewMode.slice(7) : "";
  const currentPlugin = plugins.find((plugin) => plugin.id === currentPluginId) ?? null;
  const currentPluginState = currentPluginId ? pluginState[currentPluginId] : null;
  const currentPluginLayout = currentPlugin?.layout ?? "table";
  const isChatView = viewMode === "chat";
  const dashboardSessions = useMemo(() => sessions.filter((session) => session.key.startsWith("dashboard:")), [sessions]);
  const activeChatSession = useMemo(
    () => dashboardSessions.find((session) => session.key === chatSessionKey) ?? null,
    [chatSessionKey, dashboardSessions],
  );
  const currentChatEvents = useMemo(
    () => chatEvents.filter((event) => event.session_key === chatSessionKey),
    [chatEvents, chatSessionKey],
  );

  const channels = useMemo(() => Array.from(new Set(sessions.map((session) => session.key.split(":")[0]).filter(Boolean))), [sessions]);

  useEffect(() => {
    chatEventsRef.current = chatEvents;
  }, [chatEvents]);

  const run = useCallback(async (work: () => Promise<void>) => {
    try {
      setError(null);
      await work();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    }
  }, []);

  const loadSessions = useCallback(async () => {
    const params = new URLSearchParams();
    if (sessionSearch) params.set("q", sessionSearch);
    if (sessionChannel) params.set("channel", sessionChannel);
    params.set("page_size", "200");
    const payload = asPageResult(await api<PageResult<SessionRow>>(`/api/dashboard/sessions?${params.toString()}`));
    setSessions(payload.items);
    setActiveSession((current) => {
      if (!activeSessionKey) return current;
      return payload.items.find((session) => session.key === activeSessionKey) ?? null;
    });
  }, [activeSessionKey, sessionChannel, sessionSearch]);

  const loadMessages = useCallback(async () => {
    const params = new URLSearchParams();
    if (activeSessionKey) params.set("session_key", activeSessionKey);
    if (messageSearch) params.set("q", messageSearch);
    if (messageRole) params.set("role", messageRole);
    params.set("page", String(messagePage));
    params.set("page_size", String(messagePageSize));
    params.set("sort_by", messageSortBy);
    params.set("sort_order", messageSortOrder);
    const payload = asPageResult(await api<PageResult<MessageRow>>(`/api/dashboard/messages?${params.toString()}`));
    setMessages(payload.items);
    setTotalMessages(payload.total);
    setActiveMessage((current) => current && payload.items.some((item) => item.id === current.id) ? current : null);
  }, [activeSessionKey, messagePage, messageRole, messageSearch, messageSortBy, messageSortOrder]);

  const loadProactiveOverview = useCallback(async () => {
    setProactiveOverview(await api<ProactiveOverview>("/api/dashboard/proactive/overview"));
  }, []);

  const loadChatStatus = useCallback(async () => {
    setChatStatus(await api<ChatStatus>("/api/dashboard/chat/status"));
  }, []);

  const loadChatCommands = useCallback(async () => {
    setChatCommands(await api<ChatCommandManifest>("/api/dashboard/chat/commands"));
  }, []);

  const parseChatCommand = useCallback(async (content: string, sessionKey: string): Promise<ChatCommandPreview> => {
    return api<ChatCommandPreview>("/api/dashboard/chat/commands/parse", {
      method: "POST",
      body: JSON.stringify({ content, session_key: sessionKey }),
    });
  }, []);

  const loadChatHistory = useCallback(async (sessionKey: string) => {
    const params = new URLSearchParams();
    params.set("session_key", sessionKey);
    params.set("page_size", "120");
    const payload = await api<PageResult<MessageRow> & { session_key?: string; pending_approvals?: unknown[] }>(`/api/dashboard/chat/history?${params.toString()}`);
    const history = chatHistoryToEvents(payload.items ?? []);
    const approvals = Array.isArray(payload.pending_approvals)
      ? payload.pending_approvals.map((item, index) => normalizeChatEvent(
          {
            event: "tool_approval_required",
            kind: "approval",
            label: "Approval required",
            seq: -(index + 1),
            session_key: sessionKey,
            ...((item && typeof item === "object") ? item as Record<string, unknown> : {}),
          },
          sessionKey,
          new Date().toISOString(),
        ))
      : [];
    setChatEvents((current) => {
      const otherSessions = current.filter((event) => event.session_key !== sessionKey);
      const liveForSession = current.filter((event) => event.session_key === sessionKey && shouldKeepLiveEventAfterHistoryReload(event, history));
      return [...otherSessions, ...history, ...approvals, ...liveForSession];
    });
  }, []);

  const appendChatEvent = useCallback((event: Partial<ChatEventRow> & { event: string }): void => {
    const now = new Date().toISOString();
    const row = normalizeChatEvent(event, chatSessionKey, now);
    setChatEvents((current) => mergeChatEvent(current, row));
  }, [chatSessionKey]);

  const startChatStream = useCallback(async (sessionKey: string): Promise<void> => {
    chatAbortRef.current?.abort();
    chatStreamRef.current?.cancel().catch(() => {});
    const controller = new AbortController();
    chatAbortRef.current = controller;
    setChatConnected(false);
    setChatLiveEvent("");
    const params = new URLSearchParams();
    params.set("session_key", sessionKey);
    const sinceSeq = latestChatEventSeq(chatEventsRef.current, sessionKey);
    chatSeqRef.current[sessionKey] = sinceSeq;
    if (sinceSeq > 0) params.set("since_seq", String(sinceSeq));
    let response: Response;
    try {
      response = await fetch(`/api/dashboard/chat/stream?${params.toString()}`, {
        signal: controller.signal,
        headers: { Accept: "text/event-stream" },
      });
    } catch (error) {
      if (isAbortError(error)) return;
      throw errorWithCause(chatNetworkErrorMessage(error), error);
    }
    if (!response.ok || !response.body) {
      const payload = await response.json().catch(() => ({})) as { detail?: string };
      throw new Error(payload.detail || `Request failed: ${response.status}`);
    }
    const reader = response.body.getReader();
    chatStreamRef.current = reader;
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      let result: ReadableStreamReadResult<Uint8Array>;
      try {
        result = await reader.read();
      } catch (error) {
        if (isAbortError(error)) return;
        throw error;
      }
      const { done, value } = result;
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const chunks = buffer.split("\n\n");
      buffer = chunks.pop() ?? "";
      for (const chunk of chunks) {
        const parsed = parseSseChunk(chunk);
        if (!parsed) continue;
        if (parsed.event === "connected") {
          setChatConnected(true);
          continue;
        }
        updateStoredChatSeq(sessionKey, parsed.data);
        handleChatSsePayload(parsed.event, parsed.data, {
          appendChatEvent,
          setChatSending,
          setChatLiveEvent,
        });
      }
    }
  }, [appendChatEvent]);

  const sendChatMessage = useCallback(async () => {
    const content = chatInput.trim();
    if (!content || chatSending) return;
    let preview = chatCommandPreview;
    if (content.startsWith("/")) {
      try {
        preview = await parseChatCommand(content, chatSessionKey);
        setChatCommandPreview(preview);
        setChatCommandPreviewKey(`${chatSessionKey}\n${content}`);
        chatPreviewRef.current[chatSessionKey] = preview;
      } catch (exc) {
        appendChatEvent({
          event: "error",
          kind: "error",
          label: "Command preview failed",
          detail: exc instanceof Error ? exc.message : String(exc),
          session_key: chatSessionKey,
        });
        return;
      }
      if (!preview.can_send) {
        appendChatEvent({
          event: "error",
          kind: "error",
          label: "Command requirements",
          detail: commandPreviewProblem(preview),
          session_key: chatSessionKey,
        });
        return;
      }
    }
    setChatInput("");
    setChatCommandPreview(null);
    setChatCommandPreviewKey("");
    chatPreviewRef.current[chatSessionKey] = null;
    setChatSending(true);
    appendChatEvent({
      event: "user",
      kind: "user",
      label: "You",
      content,
      detail: content,
      metadata: preview ? { command: preview, source: "dashboard_chat_command" } : undefined,
      session_key: chatSessionKey,
      source: "local",
    });
    try {
      await api("/api/dashboard/chat/messages", {
        method: "POST",
        body: JSON.stringify({ content, session_key: chatSessionKey }),
      });
      void loadSessions();
    } catch (exc) {
      setChatSending(false);
      appendChatEvent({
        event: "error",
        kind: "error",
        label: "Send failed",
        detail: exc instanceof Error ? exc.message : String(exc),
        session_key: chatSessionKey,
      });
    }
  }, [appendChatEvent, chatCommandPreview, chatInput, chatSending, chatSessionKey, loadSessions, parseChatCommand]);

  const createChatSession = useCallback(async (): Promise<void> => {
    if (creatingChat) return;
    setCreatingChat(true);
    try {
      const session = await api<SessionRow>("/api/dashboard/chat/sessions", {
        method: "POST",
        body: JSON.stringify({}),
      });
      setSessions((current) => [session, ...current.filter((item) => item.key !== session.key)]);
      setChatSessionKey(session.key);
      setChatLiveEvent("");
      setChatInput("");
      setViewMode("chat");
      setNavOpen((current) => ({ ...current, chat: true }));
      void loadChatStatus();
      void loadChatHistory(session.key);
    } finally {
      setCreatingChat(false);
    }
  }, [creatingChat, loadChatHistory, loadChatStatus]);

  const deleteChatSession = useCallback(async (session: SessionRow): Promise<void> => {
    if (deletingChatKey) return;
    setDeletingChatKey(session.key);
    try {
      await api(`/api/dashboard/sessions/${encodePath(session.key)}`, { method: "DELETE" });
      setChatEvents((current) => current.filter((event) => event.session_key !== session.key));
      setSessions((current) => current.filter((item) => item.key !== session.key));
      setChatDeleteTarget(null);
      if (chatSessionKey === session.key) {
        const nextSession = dashboardSessions
          .filter((item) => item.key !== session.key)
          .sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)))[0];
        if (nextSession) {
          setChatSessionKey(nextSession.key);
          setChatLiveEvent("");
          void loadChatHistory(nextSession.key);
        } else {
          await createChatSession();
        }
      }
      void loadSessions();
    } finally {
      setDeletingChatKey(null);
    }
  }, [chatSessionKey, createChatSession, dashboardSessions, deletingChatKey, loadChatHistory, loadSessions]);

  const decideChatApproval = useCallback(async (approvalId: string, decision: "approve" | "reject"): Promise<void> => {
    if (!approvalId) return;
    setChatApprovalState((current) => ({
      ...current,
      [approvalId]: decision === "approve" ? "approving" : "rejecting",
    }));
    try {
      await api(`/api/dashboard/chat/approvals/${encodeURIComponent(approvalId)}?session_key=${encodeURIComponent(chatSessionKey)}`, {
        method: "POST",
        body: JSON.stringify({ decision }),
      });
      setChatApprovalState((current) => ({
        ...current,
        [approvalId]: decision === "approve" ? "approved" : "rejected",
      }));
      await loadChatHistory(chatSessionKey);
      void loadSessions();
    } catch (exc) {
      setChatApprovalState((current) => ({ ...current, [approvalId]: "failed" }));
      appendChatEvent({
        event: "error",
        kind: "error",
        label: "Approval failed",
        detail: exc instanceof Error ? exc.message : String(exc),
        session_key: chatSessionKey,
      });
    }
  }, [appendChatEvent, chatSessionKey, loadChatHistory, loadSessions]);

  const openRunReviewDrawer = useCallback((runId: string, target: RunReviewDrawerState["target"] = "review"): void => {
    const cleanRunId = String(runId || "").trim();
    if (!cleanRunId) return;
    setChatReviewDrawer({
      runId: cleanRunId,
      target,
      loading: true,
      error: null,
      review: null,
      packet: null,
      trace: null,
      provenance: null,
    });
    void run(async () => {
      const [review, packet, trace, provenance] = await Promise.all([
        api<Record<string, unknown>>(`/api/biomed/answer-runs/${encodeURIComponent(cleanRunId)}/evidence-review`).catch((exc) => ({ error: exc instanceof Error ? exc.message : String(exc) })),
        api<Record<string, unknown>>(`/api/biomed/answer-runs/${encodeURIComponent(cleanRunId)}/evidence-review/packet`).catch((exc) => ({ error: exc instanceof Error ? exc.message : String(exc) })),
        api<Record<string, unknown>>(`/api/biomed/answer-runs/${encodeURIComponent(cleanRunId)}/trace`).catch((exc) => ({ error: exc instanceof Error ? exc.message : String(exc) })),
        api<Record<string, unknown>>(`/api/biomed/answer-runs/${encodeURIComponent(cleanRunId)}/provenance`).catch((exc) => ({ error: exc instanceof Error ? exc.message : String(exc) })),
      ]);
      setChatReviewDrawer({
        runId: cleanRunId,
        target,
        loading: false,
        error: null,
        review,
        packet,
        trace,
        provenance,
      });
    });
  }, [run]);

  const loadProactivePanel = useCallback(async () => {
    const params = new URLSearchParams();
    params.set("page", String(proactivePage));
    params.set("page_size", String(proactivePageSize));
    params.set("sort_by", proactiveSortBy);
    params.set("sort_order", proactiveSortOrder);
    if (proactiveSessionFilter) params.set("session_key", proactiveSessionFilter);
    if (proactiveSection === "reply" || proactiveSection === "skip") params.set("terminal_action", proactiveSection);
    if (proactiveSection === "drift" || proactiveSection === "proactive") params.set("flow", proactiveSection);
    if (["busy", "cooldown", "presence"].includes(proactiveSection)) params.set("gate_exit", proactiveSection);
    const payload = asPageResult(await api<PageResult<ProactiveTick>>(`/api/dashboard/proactive/tick_logs?${params.toString()}`));
    setProactiveItems(payload.items);
    setProactiveTotal(payload.total);
    setActiveProactiveKey((current) => current && payload.items.some((item) => item.tick_id === current) ? current : null);
  }, [proactivePage, proactiveSection, proactiveSessionFilter, proactiveSortBy, proactiveSortOrder]);

  const loadPluginPanel = useCallback(async (pluginId: string) => {
    const plugin = plugins.find((item) => item.id === pluginId);
    const state = pluginState[pluginId];
    if (!plugin || !state) return;
    const result = await plugin.fetchPage({ page: state.page, pageSize: state.pageSize, filters: state.filters, sortBy: state.sortBy, sortOrder: state.sortOrder });
    setPluginState((current) => ({
      ...current,
      [pluginId]: {
        ...current[pluginId],
        total: result.total || 0,
        items: result.items || [],
        activeRowKey: current[pluginId]?.activeRowKey && result.items.some((item) => String(item[plugin.rowKey] ?? "") === current[pluginId].activeRowKey)
          ? current[pluginId].activeRowKey
          : null,
        activeDetail: current[pluginId]?.activeRowKey && result.items.some((item) => String(item[plugin.rowKey] ?? "") === current[pluginId].activeRowKey)
          ? current[pluginId].activeDetail
          : null,
      },
    }));
  }, [pluginState, plugins]);

  const refreshCurrentView = useCallback(async () => {
    await loadSessions();
    if (viewMode === "proactive") {
      await loadProactiveOverview();
      await loadProactivePanel();
    } else if (viewMode === "chat") {
      await loadChatStatus();
    } else if (viewMode.startsWith("plugin:")) {
      await loadPluginPanel(viewMode.slice(7));
    } else {
      await loadMessages();
    }
  }, [loadChatStatus, loadMessages, loadPluginPanel, loadProactiveOverview, loadProactivePanel, loadSessions, viewMode]);

  useEffect(() => {
    const refresh = (): void => {
      void run(refreshCurrentView);
    };
    window.addEventListener("akashic-dashboard-refresh", refresh);
    return () => window.removeEventListener("akashic-dashboard-refresh", refresh);
  }, [refreshCurrentView, run]);

  useEffect(() => {
    installDashboardGlobals((plugin) => {
      setPlugins((current) => current.some((item) => item.id === plugin.id) ? current : [...current, plugin]);
      setPluginState((current) => current[plugin.id] ? current : {
        ...current,
        [plugin.id]: {
          page: 1,
          pageSize: plugin.pageSize || 25,
          total: 0,
          items: [],
          activeRowKey: null,
          activeDetail: null,
          filters: {},
          sortBy: plugin.defaultSortBy ?? "",
          sortOrder: plugin.defaultSortOrder ?? "desc",
          selectedIds: new Set(),
        },
      });
    });
    void loadPluginAssets();
  }, []);

  useEffect(() => {
    void run(async () => {
      await loadSessions();
      await loadMessages();
      await loadProactiveOverview();
      await loadChatStatus();
      await loadChatCommands();
    });
  }, [loadChatCommands, loadChatStatus, loadMessages, loadProactiveOverview, loadSessions, run]);

  useEffect(() => {
    if (!chatInput.trim().startsWith("/")) {
      setChatCommandPreview(null);
      setChatCommandPreviewKey("");
      return;
    }
    const key = `${chatSessionKey}\n${chatInput.trim()}`;
    if (chatCommandPreviewKey === key) return;
    let cancelled = false;
    setChatCommandPreviewLoading(true);
    const timer = window.setTimeout(() => {
      parseChatCommand(chatInput.trim(), chatSessionKey)
        .then((preview) => {
          if (cancelled) return;
          setChatCommandPreview(preview);
          setChatCommandPreviewKey(key);
          chatPreviewRef.current[chatSessionKey] = preview;
        })
        .catch((exc) => {
          if (cancelled) return;
          setChatCommandPreview({
            session_key: chatSessionKey,
            kind: "biomed",
            ok: false,
            command: "",
            action: "",
            arguments: {},
            missing_requirements: [],
            confirmation: null,
            final_prompt: chatInput.trim(),
            can_send: false,
            errors: [exc instanceof Error ? exc.message : String(exc)],
          });
          setChatCommandPreviewKey(key);
        })
        .finally(() => {
          if (!cancelled) setChatCommandPreviewLoading(false);
        });
    }, 180);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      setChatCommandPreviewLoading(false);
    };
  }, [chatCommandPreviewKey, chatInput, chatSessionKey, parseChatCommand]);

  useEffect(() => {
    setChatCommandPreview(chatPreviewRef.current[chatSessionKey] ?? null);
    setChatCommandPreviewKey("");
  }, [chatSessionKey]);

  useEffect(() => {
    for (const plugin of plugins) {
      void run(async () => {
        const count = await plugin.getCount();
        if (count === null) {
          setHiddenPlugins((current) => ({ ...current, [plugin.id]: true }));
        } else {
          setHiddenPlugins((current) => ({ ...current, [plugin.id]: false }));
          setPluginState((current) => ({
            ...current,
            [plugin.id]: { ...current[plugin.id], total: count },
          }));
        }
      });
    }
  }, [plugins, run]);

  const focusView = useCallback((next: ViewMode): void => {
    setViewMode(next);
    setNavOpen((current) => ({ ...current, [next]: true }));
  }, []);

  const selectView = (next: ViewMode): void => {
    focusView(next);
    void run(async () => {
      if (next === "sessions") await loadMessages();
      else if (next === "chat") await loadChatStatus();
      else if (next === "proactive") {
        await loadProactiveOverview();
        await loadProactivePanel();
      } else await loadPluginPanel(next.slice(7));
    });
  };

  const toggleNav = (kind: ViewMode): void => {
    if (viewMode !== kind) {
      selectView(kind);
      return;
    }
    setNavOpen((current) => ({ ...current, [kind]: !current[kind] }));
  };

  const sort = (scope: "messages" | "proactive", key: string): void => {
    const flip = (currentKey: string, currentOrder: SortOrder): SortOrder => currentKey === key && currentOrder === "desc" ? "asc" : "desc";
    if (scope === "messages") {
      setMessageSortOrder(flip(messageSortBy, messageSortOrder));
      setMessageSortBy(key);
      setMessagePage(1);
    } else {
      setProactiveSortOrder(flip(proactiveSortBy, proactiveSortOrder));
      setProactiveSortBy(key);
      setProactivePage(1);
    }
  };

  useEffect(() => {
    if (viewMode === "sessions") void run(loadMessages);
  }, [loadMessages, run, viewMode]);

  useEffect(() => {
    if (viewMode === "proactive") void run(loadProactivePanel);
  }, [loadProactivePanel, run, viewMode]);

  useEffect(() => {
    if (viewMode !== "chat" || !chatStatus?.enabled) return;
    void run(async () => {
      await loadChatHistory(chatSessionKey);
    });
  }, [chatSessionKey, chatStatus?.enabled, loadChatHistory, run, viewMode]);

  useEffect(() => {
    if (viewMode !== "chat" || !chatStatus?.enabled) {
      return;
    }
    void startChatStream(chatSessionKey).catch((exc) => {
      if (isAbortError(exc)) return;
      setError(exc instanceof Error ? exc.message : String(exc));
    });
    return () => {
      chatAbortRef.current?.abort();
      chatStreamRef.current?.cancel().catch(() => {});
      setChatConnected(false);
    };
  }, [chatSessionKey, chatStatus?.enabled, startChatStream, viewMode]);

  const currentPageCount = currentPluginState
    ? pageCount(currentPluginState.total, currentPluginState.pageSize)
    : viewMode === "proactive"
      ? pageCount(proactiveTotal, proactivePageSize)
      : pageCount(totalMessages, messagePageSize);

  const currentPage = currentPluginState?.page ?? (viewMode === "proactive" ? proactivePage : messagePage);

  const changePage = (delta: number): void => {
    if (currentPage + delta < 1 || currentPage + delta > currentPageCount) return;
    if (currentPluginId) {
      void run(async () => {
        const plugin = plugins.find((item) => item.id === currentPluginId);
        const state = pluginState[currentPluginId];
        if (!plugin || !state) return;
        const nextPage = state.page + delta;
        const result = await plugin.fetchPage({ page: nextPage, pageSize: state.pageSize, filters: state.filters, sortBy: state.sortBy, sortOrder: state.sortOrder });
        setPluginState((current) => ({
          ...current,
          [currentPluginId]: {
            ...current[currentPluginId],
            page: nextPage,
            total: result.total || 0,
            items: result.items || [],
            activeRowKey: null,
            activeDetail: null,
          },
        }));
      });
    } else if (viewMode === "proactive") setProactivePage((page) => page + delta);
    else setMessagePage((page) => page + delta);
  };

  // Batch count: messages or plugin selectedIds
  const pluginBatchCount = currentPluginState?.selectedIds.size ?? 0;
  const batchCount = viewMode.startsWith("plugin:") ? pluginBatchCount : selectedMessageIds.size;

  // dispatch for current plugin (used in DetailPane and batch bar)
  const currentDispatch = currentPlugin && currentPluginState
    ? makeDispatch(
        currentPlugin,
        () => pluginState[currentPlugin.id] ?? null,
        (updater) => setPluginState((c) => ({ ...c, [currentPlugin.id]: updater(c[currentPlugin.id]) })),
        () => focusView(`plugin:${currentPlugin.id}`),
      )
    : undefined;
  const isPluginWorkbench = Boolean(
    currentPlugin
      && currentPluginState
      && currentDispatch
      && currentPluginLayout === "workbench"
      && currentPlugin.renderMain,
  );

  const shellClassName = `shell${isChatView ? " chat-shell" : ""}`;

  return (
    <div className={shellClassName}>
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">A</div>
          <div>
            <div className="brand-title">Akashic</div>
            <div className="brand-sub">Agent workspace</div>
          </div>
        </div>
        <TopbarFilters
          viewMode={viewMode}
          messageSearch={messageSearch}
          setMessageSearch={(value) => { setMessageSearch(value); setMessagePage(1); }}
          messageRole={messageRole}
          setMessageRole={(value) => { setMessageRole(value); setMessagePage(1); }}
          activeSessionKey={activeSessionKey}
          clearSession={() => { setActiveSessionKey(null); setActiveSession(null); setActiveMessage(null); setMessagePage(1); }}
          proactiveSection={proactiveSection}
          proactiveSessionFilter={proactiveSessionFilter}
          clearProactiveSession={() => { setProactiveSessionFilter(""); setProactivePage(1); }}
          currentPlugin={currentPlugin}
          currentPluginState={currentPluginState}
          onSetPluginState={currentPlugin ? (updater) => setPluginState((c) => ({ ...c, [currentPlugin.id]: updater(c[currentPlugin.id]) })) : undefined}
        />
        <div className="topbar-view">
          <div className="view-chip"><span>{viewLabel(viewMode, currentPlugin)}</span></div>
          {viewMode.startsWith("plugin:") && currentPlugin?.renderTopbarAction && currentPluginState && currentDispatch && (
            <PluginTopbarAction
              plugin={currentPlugin}
              pluginId={currentPlugin.id}
              state={currentPluginState}
              onSetState={(updater) => setPluginState((c) => ({ ...c, [currentPlugin.id]: updater(c[currentPlugin.id]) }))}
              onActivate={() => focusView(`plugin:${currentPlugin.id}`)}
            />
          )}
        </div>
      </header>

      <main className={`workspace${isPluginWorkbench ? " plugin-workbench-mode" : ""}`}>
        <aside className="sessions-pane">
          <div className="pane-head">
            <div className="pane-kicker">Explorer</div>
            <div className="pane-title">
              {currentPlugin && currentPluginState
                ? (currentPlugin.countTitle ? currentPlugin.countTitle(currentPluginState.total) : `${currentPluginState.total} records`)
                : `${sessions.length} sessions`}
            </div>
          </div>
          <div className="filters-stack">
            <label className="search search-small">
              <Search size={14} aria-hidden="true" />
              <input type="text" placeholder="Filter sessions" value={sessionSearch} onChange={(event) => setSessionSearch(event.target.value.trim())} />
            </label>
            <select value={sessionChannel} onChange={(event) => setSessionChannel(event.target.value)}>
              <option value="">All channels</option>
              {channels.map((channel) => <option key={channel} value={channel}>{channel}</option>)}
            </select>
          </div>
          <nav className="explorer-nav">
            <NavGroup label="Chat" count={dashboardSessions.length} active={viewMode === "chat"} open={!!navOpen.chat} onToggle={() => toggleNav("chat")}>
              <button className="new-chat-button" type="button" disabled={creatingChat || !chatStatus?.enabled} onClick={() => void run(createChatSession)}>
                <Plus size={15} aria-hidden="true" />
                <span>{creatingChat ? "Creating..." : "New Chat"}</span>
              </button>
              <div className="session-list chat-session-list">
                {dashboardSessions.length ? dashboardSessions.map((session) => {
                  const isRunning = chatSending && chatSessionKey === session.key;
                  return (
                    <div key={session.key} className={`chat-session-row ${chatSessionKey === session.key ? "active" : ""}`}>
                      <button className="chat-session-main" type="button" onClick={() => {
                        setChatSessionKey(session.key);
                        setChatLiveEvent("");
                        selectView("chat");
                      }}>
                        <div className="nav-item-row">
                          <span className="nav-item-name">{chatSessionTitle(session)}</span>
                          <span className="nav-item-count">{session.message_count}</span>
                        </div>
                        <div className="nav-item-desc">{chatSessionSubtitle(session)}</div>
                      </button>
                      <button
                        className="chat-session-delete icon-btn"
                        type="button"
                        title={isRunning ? "Chat is running" : "Delete chat"}
                        aria-label={`Delete ${chatSessionTitle(session)}`}
                        disabled={isRunning || deletingChatKey === session.key}
                        onClick={() => setChatDeleteTarget(session)}
                      >
                        <Trash2 size={14} aria-hidden="true" />
                      </button>
                    </div>
                  );
                }) : (
                  <div className="chat-nav-empty">No chats yet.</div>
                )}
              </div>
            </NavGroup>
            <NavGroup label="Sessions" count={totalMessages || totalSessionMessages(sessions)} active={viewMode === "sessions"} open={!!navOpen.sessions} onToggle={() => toggleNav("sessions")}>
              <button className={`all-messages-row ${viewMode === "sessions" && !activeSessionKey ? "active" : ""}`} type="button" onClick={() => {
                setActiveSessionKey(null);
                setActiveSession(null);
                setActiveMessage(null);
                setMessagePage(1);
                selectView("sessions");
              }}>
                <span>All messages</span><strong>{sessions.length}</strong>
              </button>
              <div className="session-list">
                {sessions.map((session) => (
                  <button key={session.key} className={`session-item ${activeSessionKey === session.key ? "active" : ""}`} type="button" onClick={() => {
                    setActiveSessionKey(session.key);
                    setActiveSession(session);
                    setActiveMessage(null);
                    setMessagePage(1);
                    selectView("sessions");
                  }}>
                    <div className="nav-item-row">
                      <span className="nav-type-dot memory-type-profile" />
                      <span className="nav-item-name mono">{formatSessionKeyForTable(session.key)}</span>
                      <span className="nav-item-count">{session.message_count}</span>
                    </div>
                    <div className="nav-item-desc">{relativeTime(session.updated_at)}</div>
                  </button>
                ))}
              </div>
            </NavGroup>
            <NavGroup label="Proactive" count={proactiveOverview?.counts.tick_logs ?? proactiveTotal} active={viewMode === "proactive"} open={!!navOpen.proactive} onToggle={() => toggleNav("proactive")}>
              <button className={`all-messages-row ${proactiveSection === "all" && viewMode === "proactive" ? "active" : ""}`} type="button" onClick={() => { setProactiveSection("all"); setProactivePage(1); selectView("proactive"); }}>
                <span>{proactiveSectionLabel("all")}</span><strong>{proactiveSectionCount("all", proactiveOverview)}</strong>
              </button>
              <div className="proactive-quick-list">
                {["drift", "proactive", "reply", "skip", "busy", "cooldown", "presence"].map((section) => (
                  <button key={section} className={`proactive-quick-item ${proactiveSection === section ? "active" : ""}`} type="button" onClick={() => {
                    setProactiveSection(section);
                    setProactivePage(1);
                    selectView("proactive");
                  }}>
                    <div className="nav-item-row">
                      <span className="nav-item-name">{proactiveSectionLabel(section)}</span>
                      <span className="nav-item-count">{proactiveSectionCount(section, proactiveOverview)}</span>
                    </div>
                  </button>
                ))}
              </div>
            </NavGroup>
            {plugins.some((p) => !hiddenPlugins[p.id]) && (
              <div className="nav-section-divider">
                <span>Plugins</span>
              </div>
            )}
            {plugins.filter((p) => !hiddenPlugins[p.id]).map((plugin) => {
              const pState = pluginState[plugin.id];
              const pDispatch = pState
                ? makeDispatch(
                    plugin,
                    () => pluginState[plugin.id] ?? null,
                    (updater) => setPluginState((c) => ({ ...c, [plugin.id]: updater(c[plugin.id]) })),
                    () => selectView(`plugin:${plugin.id}`),
                  )
                : undefined;
              const isActive = viewMode === `plugin:${plugin.id}`;
              return (
                <NavGroup key={plugin.id} label={plugin.label} count={pState?.total ?? 0} active={isActive} open={!!navOpen[`plugin:${plugin.id}`]} onToggle={() => toggleNav(`plugin:${plugin.id}`)}>
                  {plugin.renderNavBody && pState && pDispatch
                    ? <PluginNavBody
                        plugin={plugin}
                        pluginId={plugin.id}
                        state={pState}
                        onSetState={(updater) => setPluginState((c) => ({ ...c, [plugin.id]: updater(c[plugin.id]) }))}
                        onActivate={() => focusView(`plugin:${plugin.id}`)}
                      />
                    : <button className={`all-messages-row ${isActive ? "active" : ""}`} type="button" onClick={() => selectView(`plugin:${plugin.id}`)}>
                        <span>{plugin.label}</span><strong>{pState?.total ?? 0}</strong>
                      </button>
                  }
                </NavGroup>
              );
            })}
          </nav>
        </aside>

        {isChatView ? (
          <ChatPane
            status={chatStatus}
            session={activeChatSession}
            connected={chatConnected}
            events={currentChatEvents}
            input={chatInput}
            setInput={setChatInput}
            sending={chatSending}
            liveEvent={chatLiveEvent}
            commands={chatCommands}
            commandPreview={chatCommandPreview}
            commandPreviewLoading={chatCommandPreviewLoading}
            onCreateChat={() => void run(createChatSession)}
            onDeleteChat={() => activeChatSession && setChatDeleteTarget(activeChatSession)}
            onSend={() => void run(sendChatMessage)}
            onApproval={(approvalId, decision) => void run(() => decideChatApproval(approvalId, decision))}
            approvalState={chatApprovalState}
            onOpenRunReview={openRunReviewDrawer}
            onOpenSession={() => {
              setActiveSessionKey(chatSessionKey);
              setActiveSession(sessions.find((session) => session.key === chatSessionKey) ?? null);
              setActiveMessage(null);
              setMessagePage(1);
              selectView("sessions");
            }}
          />
        ) : isPluginWorkbench && currentPlugin && currentDispatch ? (
          <section className="plugin-workbench-pane">
            <PluginMain plugin={currentPlugin} dispatch={currentDispatch} />
          </section>
        ) : (
          <>
            <section className="messages-pane">
              {batchCount > 0 && (
                <div className="batch-bar">
                  <span>已选 {batchCount} 条</span>
                  {viewMode.startsWith("plugin:") && currentPlugin?.batchActions && currentPluginState
                    ? currentPlugin.batchActions.map((action: PluginBatchAction) => (
                        <button key={action.label} className={action.className} type="button" onClick={() => void run(async () => {
                          const ids = [...currentPluginState.selectedIds];
                          await action.run(ids);
                          setPluginState((c) => ({ ...c, [currentPlugin.id]: { ...c[currentPlugin.id], selectedIds: new Set() } }));
                          await loadPluginPanel(currentPlugin.id);
                        })}>{action.label}</button>
                      ))
                    : <button className="danger-ghost" type="button" onClick={() => void run(async () => {
                        await api("/api/dashboard/messages/batch-delete", { method: "POST", body: JSON.stringify({ ids: [...selectedMessageIds] }) });
                        setSelectedMessageIds(new Set());
                        await refreshCurrentView();
                      })}>批量删除</button>
                  }
                  <button className="ghost" type="button" onClick={() => {
                    if (viewMode.startsWith("plugin:") && currentPlugin) {
                      setPluginState((c) => ({ ...c, [currentPlugin.id]: { ...c[currentPlugin.id], selectedIds: new Set() } }));
                    } else {
                      setSelectedMessageIds(new Set());
                    }
                  }}>取消选择</button>
                </div>
              )}
              <TableHead viewMode={viewMode} plugin={currentPlugin} pluginState={currentPluginState} messageSortBy={messageSortBy} messageSortOrder={messageSortOrder} proactiveSortBy={proactiveSortBy} proactiveSortOrder={proactiveSortOrder} onSort={sort} onPluginSort={currentDispatch ? (key) => currentDispatch.setSort(key) : undefined} />
              <div className="table-body">
                <Rows
                  viewMode={viewMode}
                  messages={messages}
                  proactiveItems={proactiveItems}
                  plugin={currentPlugin}
                  pluginState={currentPluginState}
                  selectedMessageIds={selectedMessageIds}
                  activeMessage={activeMessage}
                  activeProactiveKey={activeProactiveKey}
                  onSelectMessage={setActiveMessage}
                  onSelectProactive={(item) => void run(async () => {
                    setActiveProactiveKey(item.tick_id);
                    const [detail, steps] = await Promise.all([
                      api<ProactiveTick>(`/api/dashboard/proactive/tick_logs/${encodePath(item.tick_id)}`),
                      api<PageResult<ProactiveStep>>(`/api/dashboard/proactive/tick_logs/${encodePath(item.tick_id)}/steps`),
                    ]);
                    setActiveProactiveDetail(detail);
                    setActiveProactiveSteps(steps.items ?? []);
                  })}
                  onSelectPluginRow={(row) => {
                    if (!currentPlugin || !currentPluginState) return;
                    const key = String(row[currentPlugin.rowKey] ?? "");
                    void run(async () => {
                      const detail = currentPlugin.fetchDetail ? await currentPlugin.fetchDetail(row) : row;
                      setPluginState((current) => ({ ...current, [currentPlugin.id]: { ...current[currentPlugin.id], activeRowKey: key, activeDetail: detail } }));
                    });
                  }}
                  onTogglePluginRow={(id) => {
                    if (!currentPlugin) return;
                    setPluginState((c) => {
                      const ps = c[currentPlugin.id];
                      if (!ps) return c;
                      const next = new Set(ps.selectedIds);
                      if (next.has(id)) next.delete(id);
                      else next.add(id);
                      return { ...c, [currentPlugin.id]: { ...ps, selectedIds: next } };
                    });
                  }}
                  setSelectedMessageIds={setSelectedMessageIds}
                />
              </div>
              <footer className="table-foot">
                <div>{tableMeta(viewMode, totalMessages, proactiveTotal, currentPlugin, currentPluginState, proactiveSessionFilter)}</div>
                <div className="pager">
                  <button className="ghost" type="button" disabled={currentPage <= 1} onClick={() => changePage(-1)}>‹</button>
                  <span>{currentPage} / {currentPageCount}</span>
                  <button className="ghost" type="button" disabled={currentPage >= currentPageCount} onClick={() => changePage(1)}>›</button>
                </div>
              </footer>
            </section>

            <aside className="detail-pane">
              <DetailPane
                viewMode={viewMode}
                activeSession={activeSession}
                activeMessage={activeMessage}
                activeProactiveDetail={activeProactiveDetail}
                activeProactiveSteps={activeProactiveSteps}
                plugin={currentPlugin}
                pluginState={currentPluginState}
                dispatch={currentDispatch}
                setProactiveSessionFilter={(key) => { setProactiveSessionFilter(key); setProactivePage(1); selectView("proactive"); }}
              />
            </aside>
          </>
        )}
      </main>
      {error && <div className="modal-backdrop" onClick={() => setError(null)}><div className="modal"><div className="modal-title">Request failed</div><p>{error}</p><div className="modal-actions"><button className="primary" type="button" onClick={() => setError(null)}>Close</button></div></div></div>}
      {chatReviewDrawer && (
        <RunReviewDrawer
          state={chatReviewDrawer}
          onClose={() => setChatReviewDrawer(null)}
          onOpenWorkspace={() => {
            setChatReviewDrawer(null);
            selectView("plugin:biomed_evidence");
          }}
        />
      )}
      {chatDeleteTarget && (
        <div className="modal-backdrop" onClick={() => setChatDeleteTarget(null)}>
          <div className="modal" onClick={(event) => event.stopPropagation()}>
            <div className="modal-title">Delete this chat?</div>
            <p className="modal-sub">This cannot be undone.</p>
            <div className="delete-chat-preview">
              <strong>{chatSessionTitle(chatDeleteTarget)}</strong>
              <span>{chatSessionSubtitle(chatDeleteTarget)}</span>
            </div>
            <div className="modal-actions">
              <button className="ghost" type="button" onClick={() => setChatDeleteTarget(null)}>Cancel</button>
              <button
                className="danger-ghost"
                type="button"
                disabled={deletingChatKey === chatDeleteTarget.key}
                onClick={() => void run(async () => deleteChatSession(chatDeleteTarget))}
              >
                {deletingChatKey === chatDeleteTarget.key ? "Deleting..." : "Delete"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function PluginNavBody(props: {
  plugin: PluginConfig;
  pluginId: string;
  state: PluginState;
  onSetState: (updater: (s: PluginState) => PluginState) => void;
  onActivate(): void;
}): React.ReactElement {
  const ref = useRef<HTMLDivElement>(null);
  const getState = useEffectEvent(() => props.state);
  const filtersKey = JSON.stringify(props.state.filters);

  useEffect(() => {
    if (ref.current && props.plugin.renderNavBody) {
      const dispatch = makeDispatch(props.plugin, getState, props.onSetState, props.onActivate);
      props.plugin.renderNavBody(ref.current, dispatch);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtersKey, props.onActivate, props.plugin, props.pluginId, props.state.sortBy, props.state.sortOrder, props.state.total]);

  return <div ref={ref} />;
}

function PluginFilters(props: {
  plugin: PluginConfig;
  pluginId: string;
  state: PluginState;
  onSetState: (updater: (s: PluginState) => PluginState) => void;
  onActivate(): void;
}): React.ReactElement {
  const ref = useRef<HTMLDivElement>(null);
  const getState = useEffectEvent(() => props.state);
  const filtersKey = JSON.stringify(props.state.filters);

  useEffect(() => {
    if (ref.current && props.plugin.renderFilters) {
      const dispatch = makeDispatch(props.plugin, getState, props.onSetState, props.onActivate);
      props.plugin.renderFilters(ref.current, dispatch);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtersKey, props.onActivate, props.plugin, props.pluginId, props.state.sortBy, props.state.sortOrder]);

  return <div ref={ref} />;
}

function PluginTopbarAction(props: {
  plugin: PluginConfig;
  pluginId: string;
  state: PluginState;
  onSetState: (updater: (s: PluginState) => PluginState) => void;
  onActivate(): void;
}): React.ReactElement {
  const ref = useRef<HTMLDivElement>(null);
  const getState = useEffectEvent(() => props.state);
  const filtersKey = JSON.stringify(props.state.filters);

  useEffect(() => {
    if (ref.current && props.plugin.renderTopbarAction) {
      const dispatch = makeDispatch(props.plugin, getState, props.onSetState, props.onActivate);
      props.plugin.renderTopbarAction(ref.current, dispatch);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtersKey, props.onActivate, props.plugin, props.pluginId, props.state.sortBy, props.state.sortOrder]);

  return <div ref={ref} />;
}

function ChatPane(props: {
  status: ChatStatus | null;
  session: SessionRow | null;
  connected: boolean;
  events: ChatEventRow[];
  input: string;
  setInput(value: string): void;
  sending: boolean;
  liveEvent: string;
  commands: ChatCommandManifest | null;
  commandPreview: ChatCommandPreview | null;
  commandPreviewLoading: boolean;
  onCreateChat(): void;
  onDeleteChat(): void;
  onSend(): void;
  onApproval(approvalId: string, decision: "approve" | "reject"): void;
  approvalState: Record<string, "approving" | "rejecting" | "approved" | "rejected" | "failed">;
  onOpenRunReview(runId: string, target?: RunReviewDrawerState["target"]): void;
  onOpenSession(): void;
}): React.ReactElement {
  const disabled = !props.status?.enabled;
  const streamRef = useRef<HTMLDivElement>(null);
  const turns = useMemo(() => deriveChatTurns(props.events), [props.events]);
  const [expandedThinking, setExpandedThinking] = useState<Record<string, boolean>>({});
  const activeThinkingKey = props.session?.key ?? props.status?.session_key ?? "dashboard:default";
  const currentThinkingExpanded = expandedThinking[activeThinkingKey] ?? false;
  const latestContentKey = useMemo(
    () => props.events
      .filter((event) => event.kind === "user" || event.kind === "assistant" || event.event === "done")
      .map((event) => `${event.id}:${event.content ?? ""}:${event.pending ? "1" : "0"}`)
      .join("|"),
    [props.events],
  );

  useEffect(() => {
    if (disabled) return;
    const el = streamRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: props.sending ? "smooth" : "auto" });
  }, [disabled, latestContentKey, props.sending]);

  return (
    <section className="chat-pane">
      <header className="chat-head">
        <div>
          <div className="chat-title">{chatSessionTitle(props.session)}</div>
          <div className="chat-subtitle">
            <span className={`chat-dot ${props.connected && !disabled ? "on" : ""}`} />
            <span>{disabled ? "Disconnected" : props.sending ? "Running" : "Connected"}</span>
            {props.session?.key && <code>{props.session.key}</code>}
          </div>
        </div>
        <div className="chat-head-actions">
          <button className="ghost" type="button" onClick={props.onCreateChat} disabled={disabled}>
            <Plus size={14} aria-hidden="true" />
            <span>New Chat</span>
          </button>
          <button className="ghost" type="button" onClick={props.onDeleteChat} disabled={disabled || props.sending || !props.session}>
            <Trash2 size={14} aria-hidden="true" />
            <span>Delete</span>
          </button>
          {props.session?.key && (
            <button className="ghost" type="button" title="Copy session key" onClick={() => void copySessionKey(props.session!.key)}>
              <Copy size={14} aria-hidden="true" />
              <span>Copy key</span>
            </button>
          )}
          <button className="ghost" type="button" onClick={props.onOpenSession} disabled={!props.session}>
            <Info size={14} aria-hidden="true" />
            <span>Session details</span>
          </button>
        </div>
      </header>
      <CommandQuickStart
        setInput={props.setInput}
      />
      {disabled ? (
        <div className="chat-disabled">
          <div className="detail-empty-title">Full runtime is not enabled</div>
          <div className="detail-empty-text">{props.status?.reason || "Dashboard Chat requires python main.py."}</div>
        </div>
      ) : (
        <>
          <div className="chat-stream" ref={streamRef}>
            {turns.length ? turns.map((turn, index) => (
              <ChatTurnItem
                key={`${turn.session_key}-${turn.user?.id ?? turn.assistant?.id ?? turn.thinking?.updatedAt ?? index}`}
                turn={turn}
                expanded={currentThinkingExpanded}
                onToggleThinking={() => setExpandedThinking((current) => ({
                  ...current,
                  [activeThinkingKey]: !currentThinkingExpanded,
                }))}
                onApproval={props.onApproval}
                approvalState={props.approvalState}
                onOpenRunReview={props.onOpenRunReview}
              />
            )) : (
              <div className="chat-empty">
                <div className="chat-empty-kicker">Agent Console</div>
                <div className="chat-empty-title">Start a session with the agent.</div>
                <div className="chat-empty-text">Responses stream through the same runtime, tools, guardrails, and session history used by other agent channels.</div>
                <div className="chat-empty-prompts">
                  {[
                    "Summarize the current workspace state.",
                    "List the next useful steps for this session.",
                    "Check recent memory for relevant context.",
                  ].map((prompt) => (
                    <button key={prompt} type="button" onClick={() => props.setInput(prompt)}>{prompt}</button>
                  ))}
                </div>
              </div>
            )}
            {props.sending && (
              <div className="chat-running-row">
                <span className="status-pill"><LoaderCircle size={12} aria-hidden="true" /></span>
                <span>{props.liveEvent || "Working on the response"}</span>
              </div>
            )}
          </div>
          <div className="chat-composer-shell">
            {props.input.trim().startsWith("/") && (
              <CommandPalette commands={props.commands} setInput={props.setInput} />
            )}
            {props.commandPreview && <CommandPreviewCard preview={props.commandPreview} loading={props.commandPreviewLoading} />}
            <form className="chat-composer" onSubmit={(event) => { event.preventDefault(); props.onSend(); }}>
              <textarea
                value={props.input}
                placeholder="Type /biomed to run a Biomedical Evidence workflow..."
                onChange={(event) => props.setInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    props.onSend();
                  }
                }}
                disabled={props.sending}
              />
              <button className="primary" type="submit" disabled={props.sending || !props.input.trim() || Boolean(props.commandPreview && !props.commandPreview.can_send)}>
                {props.sending ? "Sending" : "Send"}
              </button>
            </form>
          </div>
        </>
      )}
    </section>
  );
}

function CommandPreviewCard(props: {
  preview: ChatCommandPreview;
  loading: boolean;
}): React.ReactElement {
  const status = commandPreviewStatusLabel(props.preview);
  const commandLabel = props.preview.command || "Command";
  return (
    <div className={`command-preview-card ${props.preview.can_send ? "ready" : "blocked"}`}>
      <div className="command-preview-head">
        <div>
          <span className="status-pill">{props.loading ? "Checking" : status}</span>
          <strong>{commandLabel} {props.preview.action && <span>{props.preview.action.replaceAll("_", " ")}</span>}</strong>
        </div>
        {props.preview.tool_name && <code>{humanizeToolName(props.preview.tool_name)}</code>}
      </div>
      <div className="command-requirements">
        {props.preview.readiness && (
          <>
            <span className={`requirement-chip ${props.preview.readiness.pubmed.status === "enabled" ? "ok" : "warn"}`}>PubMed policy {props.preview.readiness.pubmed.status}</span>
            <span className={`requirement-chip ${props.preview.readiness.llm_provider.status === "configured" ? "ok" : "warn"}`}>LLM {props.preview.readiness.llm_provider.status}</span>
          </>
        )}
        {props.preview.confirmation && <span className="requirement-chip warn">Confirmation required</span>}
        {!props.preview.confirmation && <span className="requirement-chip ok">No confirmation</span>}
      </div>
      {props.preview.missing_requirements.length > 0 && (
        <div className="command-preview-list">
          {props.preview.missing_requirements.map((item) => (
            <div key={`${item.kind}-${item.label}`} className="command-preview-issue">
              <strong>{item.label}</strong>
              <span>{item.detail}</span>
            </div>
          ))}
        </div>
      )}
      {props.preview.errors.length > 0 && (
        <div className="command-preview-list">
          {props.preview.errors.map((error) => <div key={error} className="command-preview-issue"><strong>Syntax</strong><span>{error}</span></div>)}
        </div>
      )}
      <PlanPreviewDetails plan={props.preview.plan_preview} />
      {props.preview.can_send && (
        <div className="command-final-prompt">{props.preview.final_prompt}</div>
      )}
    </div>
  );
}

function PlanPreviewDetails(props: {
  plan: ChatCommandPlanPreview | null | undefined;
}): React.ReactElement {
  const plan = props.plan;
  if (!plan) return <></>;
  const phases = Array.isArray(plan.phases) ? plan.phases : [];
  const artifacts = Array.isArray(plan.expected_artifacts) ? plan.expected_artifacts : [];
  return (
    <div className="command-plan-preview">
      <div className="command-plan-grid">
        <div><span>Question</span><strong>{plan.question || "Missing"}</strong></div>
        <div><span>Source</span><strong>{plan.source || "mock"}</strong></div>
        <div><span>Papers</span><strong>{plan.paper_count ?? "Unknown"}</strong></div>
        <div><span>LLM</span><strong>{plan.llm_mode || "off"}</strong></div>
      </div>
      {phases.length > 0 && (
        <div className="command-plan-row">
          <span>Phases</span>
          <div>{phases.map((phase) => <code key={phase}>{phase}</code>)}</div>
        </div>
      )}
      {artifacts.length > 0 && (
        <div className="command-plan-row">
          <span>Artifacts</span>
          <div>{artifacts.map((artifact) => <code key={artifact}>{artifact}</code>)}</div>
        </div>
      )}
    </div>
  );
}

function CommandQuickStart(props: {
  setInput(value: string): void;
}): React.ReactElement {
  const frequent = biomedCommandSuggestions().filter((item) => item.label === "Help" || item.label === "Status" || item.label === "Mock audit" || item.label === "Live audit");
  return (
    <div className="command-rail">
      <div className="command-rail-tag">/biomed</div>
      <div className="command-chip-row">
        {frequent.map((item) => (
          <button key={`chip-${item.label}`} type="button" className="command-chip" onClick={() => props.setInput(item.command)}>
            {item.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function CommandPalette(props: {
  commands: ChatCommandManifest | null;
  setInput(value: string): void;
}): React.ReactElement {
  const suggestions = biomedCommandSuggestions();
  const hasManifest = Boolean(props.commands?.commands?.length);
  return (
    <div className="command-palette">
      <div className="command-palette-head">
        <strong>Available commands</strong>
        <span>{hasManifest ? "Biomedical Evidence command pack is loaded." : "Loading command pack..."}</span>
      </div>
      <div className="command-palette-list">
        {suggestions.map((item) => (
          <button key={item.label} type="button" className="command-palette-row" onClick={() => props.setInput(item.command)}>
            <span>{item.label}</span>
            <small>{item.description}</small>
            <code>{item.command}</code>
          </button>
        ))}
      </div>
    </div>
  );
}

function biomedCommandSuggestions(): Array<{ label: string; description: string; command: string }> {
  return [
    {
      label: "Help",
      description: "Show the concise command guide.",
      command: "/biomed help",
    },
    {
      label: "Status",
      description: "Check LLM, PubMed, export, and confirmation readiness.",
      command: "/biomed status",
    },
    {
      label: "Enable PubMed",
      description: "Turn on live PubMed command execution in config.toml.",
      command: "/biomed enable pubmed",
    },
    {
      label: "Check PubMed",
      description: "Verify whether live PubMed access is ready.",
      command: "/biomed check pubmed",
    },
    {
      label: "Mock audit",
      description: "Run a deterministic 10-paper audit without live PubMed.",
      command: '/biomed audit "microglia Alzheimer disease progression" --source mock --papers 10',
    },
    {
      label: "Live audit",
      description: "Run PubMed + all configured LLM stages.",
      command: '/biomed audit "microglia Alzheimer disease progression" --source pubmed --papers 10 --llm all --support-refute',
    },
    {
      label: "Literature",
      description: "Retrieve papers only, without synthesis.",
      command: '/biomed literature "TREM2 microglia Alzheimer" --source pubmed --papers 10',
    },
    {
      label: "Review run",
      description: "Open a saved Run Evidence Review.",
      command: "/biomed review biomed-run-...",
    },
    {
      label: "Provenance",
      description: "Prepare provenance export for a run.",
      command: "/biomed export provenance biomed-run-...",
    },
    {
      label: "Create project",
      description: "Create a research project after confirmation.",
      command: '/biomed project create "Microglia AD" --question "What links microglial activation to AD progression?"',
    },
    {
      label: "Create watch",
      description: "Create a literature watch after confirmation.",
      command: '/biomed watch create "Microglia AD" --query "microglia Alzheimer disease progression"',
    },
    {
      label: "Delete watch",
      description: "Remove a research watch and cancel its framework schedule.",
      command: "/biomed watch delete watch-...",
    },
  ];
}

function ChatTurnItem(props: {
  turn: ChatTurn;
  expanded: boolean;
  onToggleThinking(): void;
  onApproval(approvalId: string, decision: "approve" | "reject"): void;
  approvalState: Record<string, "approving" | "rejecting" | "approved" | "rejected" | "failed">;
  onOpenRunReview(runId: string, target?: RunReviewDrawerState["target"]): void;
}): React.ReactElement {
  const artifacts = useMemo(() => chatTurnRunArtifacts(props.turn), [props.turn]);
  const approvalId = extractTurnApprovalId(props.turn);
  return (
    <div className="chat-turn">
      {props.turn.user && (
        <div className="chat-message user">
          <div className="chat-bubble">{props.turn.user.content || props.turn.user.detail}</div>
        </div>
      )}
      {props.turn.thinking && props.turn.thinking.status !== "idle" && (
        <ThinkingPanel state={props.turn.thinking} expanded={props.expanded} onToggle={props.onToggleThinking} />
      )}
      {props.turn.assistant && (props.turn.assistant.content || props.turn.assistant.detail || props.turn.assistant.pending) && (
        <div className={`chat-message assistant${props.turn.assistant.pending ? " pending" : ""}`}>
          <div className="chat-bubble" dangerouslySetInnerHTML={{ __html: renderMarkdown(props.turn.assistant.content || props.turn.assistant.detail || " ") }} />
        </div>
      )}
      {(artifacts.run_id || artifacts.watch_id) && (
        <ArtifactActionBar
          artifacts={artifacts}
          onOpenRunReview={props.onOpenRunReview}
        />
      )}
      {props.turn.approval && (
        <ApprovalCard event={props.turn.approval} approvalId={approvalId} state={props.approvalState[approvalId]} onDecision={props.onApproval} />
      )}
      {props.turn.error && (
        <div className="chat-error-card">
          <span className="status-pill proactive-result-busy">error</span>
          <span>{props.turn.error.summary || props.turn.error.detail}</span>
          {props.turn.error.recovery?.label && (
            <small>
              {props.turn.error.recovery.label}
              {props.turn.error.recovery.retryable ? " This action can be retried." : ""}
            </small>
          )}
        </div>
      )}
      {props.turn.warning && (
        <div className="chat-error-card warning">
          <span className="status-pill proactive-result-idle">warning</span>
          <span>{props.turn.warning.summary || props.turn.warning.detail}</span>
        </div>
      )}
    </div>
  );
}

function ArtifactActionBar(props: {
  artifacts: ChatRunArtifacts;
  onOpenRunReview(runId: string, target?: RunReviewDrawerState["target"]): void;
}): React.ReactElement {
  const runId = String(props.artifacts.run_id || "").trim();
  const watchId = String(props.artifacts.watch_id || "").trim();
  if (!runId && !watchId) return <></>;
  if (watchId && !runId) {
    return (
      <div className="run-action-bar">
        <div className="run-action-title">
          <FileText size={14} aria-hidden="true" />
          <div>
            <strong>Research watch created</strong>
            <code>{watchId}</code>
          </div>
        </div>
        <div className="run-action-buttons">
          <button className="ghost" type="button" onClick={() => void copySessionKey(watchId)}>
            <Copy size={13} aria-hidden="true" />
            <span>Copy watch ID</span>
          </button>
        </div>
      </div>
    );
  }
  return (
    <div className="run-action-bar">
      <div className="run-action-title">
        <FileText size={14} aria-hidden="true" />
        <div>
          <strong>Review this run</strong>
          <code>{runId}</code>
        </div>
      </div>
      <div className="run-action-buttons">
        <button className="ghost" type="button" onClick={() => props.onOpenRunReview(runId, "review")}>Open review</button>
        <button className="ghost" type="button" onClick={() => props.onOpenRunReview(runId, "packet")}>Evidence packet</button>
        <button className="ghost" type="button" onClick={() => props.onOpenRunReview(runId, "provenance")}>Provenance</button>
        <button className="ghost" type="button" onClick={() => props.onOpenRunReview(runId, "trace")}>Trace</button>
        <button className="ghost" type="button" onClick={() => void copySessionKey(runId)}>
          <Copy size={13} aria-hidden="true" />
          <span>Copy run ID</span>
        </button>
      </div>
    </div>
  );
}

function ApprovalCard(props: {
  event: ChatEventRow;
  approvalId: string;
  state?: "approving" | "rejecting" | "approved" | "rejected" | "failed";
  onDecision(approvalId: string, decision: "approve" | "reject"): void;
}): React.ReactElement {
  const approvalId = props.approvalId || extractApprovalId(props.event);
  const toolName = props.event.tool_name || "tool";
  const status = props.state || props.event.status || "pending";
  const pending = status === "pending" || status === "failed";
  const busy = status === "approving" || status === "rejecting";
  const missingExecutableApproval = !approvalId;
  const resolved = status === "approved" || status === "rejected";
  const statusLabel = status === "approving"
    ? "Approving..."
    : status === "rejecting"
      ? "Rejecting..."
      : status === "approved"
        ? "Approved"
        : status === "rejected"
          ? "Rejected"
          : status === "failed"
            ? "Approval failed"
            : "Confirm action";
  return (
    <div className="approval-card">
      <div className="approval-card-body">
        <span className="status-pill proactive-result-busy">approval</span>
        <div>
          <strong>{statusLabel}</strong>
          <p>{toolName} requires confirmation before it can run.</p>
          {approvalId && <small>Approval ID: {approvalId}</small>}
          {missingExecutableApproval && <small>This approval is missing its executable approval ID. Retry the command to create a fresh approval.</small>}
          {props.event.detail && <small>{props.event.detail}</small>}
        </div>
      </div>
      <div className="approval-card-actions">
        {resolved ? (
          <span className="approval-card-missing">{status === "approved" ? "Approved" : "Rejected"}</span>
        ) : missingExecutableApproval ? (
          <span className="approval-card-missing">Not executable</span>
        ) : (
          <>
            <button type="button" className="ghost" disabled={!pending || busy} onClick={() => props.onDecision(approvalId, "reject")}>
              {status === "rejecting" ? "Rejecting" : "Reject"}
            </button>
            <button type="button" className="primary compact" disabled={!pending || busy} onClick={() => props.onDecision(approvalId, "approve")}>
              {status === "approving" ? "Approving" : "Approve"}
            </button>
          </>
        )}
      </div>
    </div>
  );
}

function RunReviewDrawer(props: {
  state: RunReviewDrawerState;
  onClose(): void;
  onOpenWorkspace(): void;
}): React.ReactElement {
  const review = props.state.review ?? {};
  const trace = props.state.trace ?? {};
  const packet = props.state.packet ?? {};
  const provenance = props.state.provenance ?? {};
  const claims = reviewClaims(review, packet).slice(0, 5);
  const warnings = collectReviewWarnings(review, trace, packet).slice(0, 6);
  const status = stringFromUnknown(review.status)
    || stringFromUnknown(review.review_status)
    || stringFromUnknown(packet.status)
    || stringFromUnknown(trace.status)
    || (props.state.loading ? "Loading" : "Available");
  const source = stringFromUnknown(review.source)
    || stringFromUnknown(review.source_policy)
    || stringFromUnknown(trace.source)
    || stringFromUnknown(packet.source)
    || stringFromUnknown(packet.source_policy)
    || "Unknown";
  const paperCount = numberFromUnknown(review.paper_count)
    ?? numberFromUnknown(review.papers_retrieved)
    ?? numberFromUnknown(review.retrieved_paper_count)
    ?? numberFromUnknown(trace.paper_count)
    ?? numberFromUnknown(packet.paper_count)
    ?? numberFromUnknown(packet.retrieved_paper_count)
    ?? countNestedItems(packet, ["papers", "citations"]);
  const verdict = stringFromUnknown(review.audit_verdict)
    || stringFromUnknown(review.verdict)
    || stringFromUnknown(review.recommended_action)
    || nestedString(review, "audit", "recommended_action")
    || nestedString(review, "audit", "verdict")
    || stringFromUnknown(packet.recommended_action)
    || stringFromUnknown(packet.audit_verdict)
    || "Review recommended";
  const activeArtifactLabel = {
    review: "Review summary",
    packet: "Evidence packet",
    provenance: "Provenance",
    trace: "Trace",
  }[props.state.target];
  return (
    <div className="review-drawer-backdrop" onClick={props.onClose}>
      <aside className="review-drawer" onClick={(event) => event.stopPropagation()}>
        <header className="review-drawer-head">
          <div>
            <div className="review-drawer-kicker">Run Evidence Review</div>
            <h2>{props.state.runId}</h2>
            <div className="review-drawer-target">{{
              review: "Review summary",
              packet: "Evidence packet",
              provenance: "Provenance",
              trace: "Trace",
            }[props.state.target]}</div>
          </div>
          <button className="ghost" type="button" onClick={props.onClose}>Close</button>
        </header>
        {props.state.loading ? (
          <div className="review-drawer-loading">
            <LoaderCircle size={16} aria-hidden="true" className="spin" />
            <span>Loading review artifacts...</span>
          </div>
        ) : (
          <>
            <div className="review-drawer-grid">
              <ReviewMetric label="Status" value={status} />
              <ReviewMetric label="Source" value={source} />
              <ReviewMetric label="Papers" value={paperCount === undefined ? "Unknown" : String(paperCount)} />
              <ReviewMetric label="Audit" value={verdict} />
            </div>
            <section className="review-drawer-section">
              <h3>{activeArtifactLabel}</h3>
              <p className="muted-text">{artifactSummary(props.state.target, review, packet, trace, provenance)}</p>
            </section>
            {warnings.length > 0 && (
              <section className="review-drawer-section">
                <h3>Warnings</h3>
                <ul>
                  {warnings.map((warning) => <li key={warning}>{warning}</li>)}
                </ul>
              </section>
            )}
            <section className="review-drawer-section">
              <h3>Claims and evidence</h3>
              {claims.length ? (
                <div className="review-claim-list">
                  {claims.map((claim, index) => (
                    <div key={`${props.state.runId}-claim-${index}`} className="review-claim-card">
                      <strong>{stringFromUnknown(claim.claim) || stringFromUnknown(claim.text) || stringFromUnknown(claim.claim_text) || `Claim ${index + 1}`}</strong>
                      <span>{claimEvidenceSummary(claim)}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="muted-text">No claim cards were returned by the lightweight review endpoint.</p>
              )}
            </section>
            <section className="review-drawer-section">
              <h3>Artifacts</h3>
              <div className="review-artifact-links">
                <a href={`/api/biomed/answer-runs/${encodeURIComponent(props.state.runId)}/evidence-review`} target="_blank" rel="noreferrer">Review JSON <ExternalLink size={12} aria-hidden="true" /></a>
                <a href={`/api/biomed/answer-runs/${encodeURIComponent(props.state.runId)}/evidence-review/packet`} target="_blank" rel="noreferrer">Evidence packet <ExternalLink size={12} aria-hidden="true" /></a>
                <a href={`/api/biomed/answer-runs/${encodeURIComponent(props.state.runId)}/trace`} target="_blank" rel="noreferrer">Trace <ExternalLink size={12} aria-hidden="true" /></a>
                <a href={`/api/biomed/answer-runs/${encodeURIComponent(props.state.runId)}/provenance`} target="_blank" rel="noreferrer">Provenance <ExternalLink size={12} aria-hidden="true" /></a>
                <a href={`/api/biomed/export?run_id=${encodeURIComponent(props.state.runId)}&report_type=pilot&format=markdown`} target="_blank" rel="noreferrer">Pilot Report <ExternalLink size={12} aria-hidden="true" /></a>
                <a href={`/api/biomed/export?run_id=${encodeURIComponent(props.state.runId)}&report_type=pilot&format=json`} target="_blank" rel="noreferrer">Pilot JSON <ExternalLink size={12} aria-hidden="true" /></a>
                <a href={`/api/biomed/answer-runs/${encodeURIComponent(props.state.runId)}/argument-graph`} target="_blank" rel="noreferrer">Argument Graph <ExternalLink size={12} aria-hidden="true" /></a>
                <a href={`/api/biomed/answer-runs/${encodeURIComponent(props.state.runId)}/evidence-graph`} target="_blank" rel="noreferrer">Evidence Graph <ExternalLink size={12} aria-hidden="true" /></a>
              </div>
            </section>
            <div className="review-drawer-actions">
              <button className="ghost" type="button" onClick={() => void copySessionKey(props.state.runId)}>Copy run ID</button>
              <button className="primary compact" type="button" onClick={props.onOpenWorkspace}>Open Biomedical Evidence</button>
            </div>
            {props.state.error && <div className="chat-error-card"><span className="status-pill proactive-result-busy">error</span><span>{props.state.error}</span></div>}
            {hasArtifactError(provenance) && <p className="muted-text">Some optional artifacts are unavailable for this run.</p>}
          </>
        )}
      </aside>
    </div>
  );
}

function ReviewMetric(props: { label: string; value: string }): React.ReactElement {
  return (
    <div className="review-metric">
      <span>{props.label}</span>
      <strong>{props.value}</strong>
    </div>
  );
}

function ThinkingPanel(props: {
  state: ChatThinkingState;
  expanded: boolean;
  onToggle(): void;
}): React.ReactElement {
  const [showAllSteps, setShowAllSteps] = useState(false);
  const statusLabel = props.state.status === "done"
    ? "Completed"
    : props.state.status === "error"
      ? "Failed"
      : "Working";
  const latestStep = props.state.steps[props.state.steps.length - 1] || props.state.summary || "Working";
  const visibleSteps = showAllSteps ? props.state.steps : props.state.steps.slice(0, 6);
  const hiddenStepCount = Math.max(0, props.state.steps.length - visibleSteps.length);
  return (
    <div className={`thinking-panel ${props.expanded ? "expanded" : "collapsed"}`}>
      <button type="button" className="thinking-panel-head" onClick={props.onToggle}>
        <div className="thinking-panel-summary">
          <LoaderCircle size={13} aria-hidden="true" className={props.state.status === "running" ? "spin" : ""} />
          <span>{statusLabel}</span>
          <strong>{props.state.status === "done" ? props.state.summary : latestStep}</strong>
        </div>
        <div className="thinking-panel-meta">
          {props.state.steps.length > 0 && <span>{props.state.steps.length} steps</span>}
          <ChevronDown size={13} aria-hidden="true" className={props.expanded ? "open" : ""} />
        </div>
      </button>
      {props.expanded && (
        <div className="thinking-panel-body">
          {visibleSteps.length ? visibleSteps.map((step, index) => (
            <div key={`${step}-${index}`} className="thinking-step">
              <span className="status-pill">step {index + 1}</span>
              <span>{step}</span>
            </div>
          )) : (
            <div className="muted-text">No internal steps were captured.</div>
          )}
          {hiddenStepCount > 0 && (
            <button className="thinking-more" type="button" onClick={() => setShowAllSteps(true)}>
              Show all steps ({props.state.steps.length})
            </button>
          )}
          {props.state.technicalDetail && (
            <details className="thinking-detail">
              <summary>Technical details</summary>
              <pre>{props.state.technicalDetail}</pre>
            </details>
          )}
        </div>
      )}
    </div>
  );
}

function TopbarFilters(props: {
  viewMode: ViewMode;
  messageSearch: string;
  setMessageSearch(value: string): void;
  messageRole: string;
  setMessageRole(value: string): void;
  activeSessionKey: string | null;
  clearSession(): void;
  proactiveSection: string;
  proactiveSessionFilter: string;
  clearProactiveSession(): void;
  currentPlugin: PluginConfig | null;
  currentPluginState: PluginState | null;
  onSetPluginState?: (updater: (s: PluginState) => PluginState) => void;
}): React.ReactElement {
  return (
    <div className="topbar-filters">
      {props.viewMode.startsWith("plugin:") && props.currentPlugin?.renderFilters && props.currentPluginState && props.onSetPluginState
        ? <PluginFilters
            plugin={props.currentPlugin}
            pluginId={props.currentPlugin.id}
            state={props.currentPluginState}
            onSetState={props.onSetPluginState}
            onActivate={() => {}}
          />
        : props.viewMode === "proactive" ? (
          <div className="filter-row">
            <div className="active-session-chip"><span>result</span><code>{proactiveSectionLabel(props.proactiveSection)}</code></div>
            {props.proactiveSessionFilter && <Chip label="session" value={props.proactiveSessionFilter} onClear={props.clearProactiveSession} />}
          </div>
        ) : props.viewMode === "chat" ? (
          <div className="filter-row">
            <div className="active-session-chip"><span>mode</span><code>chat</code></div>
          </div>
        ) : (
          <div className="filter-row">
            <label className="search"><span>⌕</span><input type="text" placeholder="搜索消息内容" value={props.messageSearch} onChange={(event) => props.setMessageSearch(event.target.value.trim())} /></label>
            <select value={props.messageRole} onChange={(event) => props.setMessageRole(event.target.value)}>
              <option value="">全部 role</option><option value="user">user</option><option value="assistant">assistant</option><option value="system">system</option><option value="tool">tool</option>
            </select>
            {props.activeSessionKey && <Chip label="session" value={props.activeSessionKey} onClear={props.clearSession} />}
          </div>
        )
      }
    </div>
  );
}

function Chip(props: { label: string; value: string; onClear(): void }): React.ReactElement {
  return <div className="active-session-chip"><span>{props.label}</span><code>{props.value}</code><button type="button" onClick={props.onClear}>×</button></div>;
}

function NavGroup(props: { label: string; count: number; active: boolean; open: boolean; onToggle(): void; children: React.ReactNode }): React.ReactElement {
  return (
    <section className={`nav-group${props.active ? " active" : ""}${props.open ? " open" : ""}`}>
      <button className="nav-group-toggle" type="button" onClick={props.onToggle}>
        <span className="nav-group-caret">▸</span>
        <span className="nav-group-label">{props.label}</span>
        <span className="nav-group-count">{props.count}</span>
      </button>
      <div className={`nav-group-body${props.open ? " open" : ""}`}>
        <div className="nav-group-body-inner">{props.children}</div>
      </div>
    </section>
  );
}

function TableHead(props: {
  viewMode: ViewMode;
  plugin: PluginConfig | null;
  pluginState: PluginState | null;
  messageSortBy: string;
  messageSortOrder: SortOrder;
  proactiveSortBy: string;
  proactiveSortOrder: SortOrder;
  onSort(scope: "messages" | "proactive", key: string): void;
  onPluginSort?: (key: string) => void;
}): React.ReactElement {
  if (props.viewMode.startsWith("plugin:") && props.plugin) {
    const hasBatch = Boolean(props.plugin.batchActions?.length);
    const grid = (hasBatch ? "32px " : "") + gridTemplate(props.plugin.columns);
    const sortBy = props.pluginState?.sortBy ?? "";
    const sortOrder = props.pluginState?.sortOrder ?? "desc";
    return (
      <div className="table-head" style={{ gridTemplateColumns: grid }}>
        {hasBatch && <div />}
        {props.plugin.columns.map((col) => col.sortable && props.onPluginSort
          ? <SortHead key={col.key} label={col.label} active={sortBy === col.key} order={sortOrder} onClick={() => props.onPluginSort!(col.key)} />
          : <div key={col.key}>{col.label}</div>
        )}
      </div>
    );
  }
  if (props.viewMode === "proactive") {
    return <div className="table-head mode-proactive-ticks">
      <SortHead label="Session" active={props.proactiveSortBy === "session_key"} order={props.proactiveSortOrder} onClick={() => props.onSort("proactive", "session_key")} />
      <SortHead label="Started" active={props.proactiveSortBy === "started_at"} order={props.proactiveSortOrder} onClick={() => props.onSort("proactive", "started_at")} />
      <SortHead label="Result" active={props.proactiveSortBy === "terminal_action"} order={props.proactiveSortOrder} onClick={() => props.onSort("proactive", "terminal_action")} />
      <div>Summary</div><div />
    </div>;
  }
  return <div className="table-head mode-messages">
    <div />
    <SortHead label="Session Key" active={props.messageSortBy === "session_key"} order={props.messageSortOrder} onClick={() => props.onSort("messages", "session_key")} />
    <SortHead label="Seq" active={props.messageSortBy === "seq"} order={props.messageSortOrder} onClick={() => props.onSort("messages", "seq")} />
    <div>Content</div>
    <SortHead label="Timestamp" active={props.messageSortBy === "ts"} order={props.messageSortOrder} onClick={() => props.onSort("messages", "ts")} />
    <SortHead label="Role" active={props.messageSortBy === "role"} order={props.messageSortOrder} onClick={() => props.onSort("messages", "role")} />
    <div />
  </div>;
}

function SortHead(props: { label: string; active: boolean; order: SortOrder; onClick(): void }): React.ReactElement {
  return <button className={`table-sort-btn ${props.active ? "active" : ""}`} type="button" onClick={props.onClick}><span>{props.label}</span><span className="table-sort-arrow">{props.active ? props.order === "asc" ? "↑" : "↓" : ""}</span></button>;
}

function Rows(props: {
  viewMode: ViewMode;
  messages: MessageRow[];
  proactiveItems: ProactiveTick[];
  plugin: PluginConfig | null;
  pluginState: PluginState | null;
  selectedMessageIds: Set<string>;
  activeMessage: MessageRow | null;
  activeProactiveKey: string | null;
  onSelectMessage(item: MessageRow): void;
  onSelectProactive(item: ProactiveTick): void;
  onSelectPluginRow(row: Record<string, unknown>): void;
  onTogglePluginRow(id: string): void;
  setSelectedMessageIds(value: Set<string>): void;
}): React.ReactElement {
  if (props.viewMode.startsWith("plugin:") && props.plugin && props.pluginState) {
    const hasBatch = Boolean(props.plugin.batchActions?.length);
    const grid = (hasBatch ? "32px " : "") + gridTemplate(props.plugin.columns);
    return <>{props.pluginState.items.length ? props.pluginState.items.map((item) => {
      const key = String(item[props.plugin!.rowKey] ?? "");
      const isSelected = props.pluginState!.selectedIds.has(key);
      return <div key={key} className={`table-row ${props.pluginState!.activeRowKey === key ? "active" : ""} ${isSelected ? "selected" : ""} ${props.plugin!.rowClass?.(item) ?? ""}`} style={{ gridTemplateColumns: grid }} onClick={() => props.onSelectPluginRow(item)}>
        {hasBatch && (
          <label className="checkbox-cell" onClick={(event) => event.stopPropagation()}>
            <input type="checkbox" checked={isSelected} onChange={() => props.onTogglePluginRow(key)} />
          </label>
        )}
        {props.plugin!.columns.map((col) => {
          const cellClass = columnCellClass(col);
          if (col.renderCell) {
            return <div key={col.key} className={cellClass} title={col.rawTitle ? String(item[col.key] ?? "") : undefined} dangerouslySetInnerHTML={{ __html: col.renderCell(item[col.key], item) }} />;
          }
          return <div key={col.key} className={cellClass} title={col.rawTitle ? String(item[col.key] ?? "") : undefined}>{formatPluginCell(props.plugin!, col, item)}</div>;
        })}
      </div>;
    }) : <div className="empty-state">{props.plugin.emptyMessage || "暂无记录。"}</div>}</>;
  }
  if (props.viewMode === "proactive") {
    return <>{props.proactiveItems.map((item) => <div key={item.tick_id} className={`table-row mode-proactive-ticks ${props.activeProactiveKey === item.tick_id ? "active" : ""}`} onClick={() => props.onSelectProactive(item)}>
      <div className="cell-session mono">{formatSessionKeyForTable(item.session_key)}</div>
      <div className="cell-time">{shortTs(item.started_at)}</div>
      <div className="proactive-status-cell"><span className={`status-pill proactive-result-${proactiveResultLabel(item)}`}>{proactiveResultLabel(item)}</span><span className={`type-pill proactive-flow-${proactiveFlowLabel(item).toLowerCase()}`}>{proactiveFlowLabel(item)}</span></div>
      <div className="content-preview">{proactiveTickPreview(item)}</div>
      <div />
    </div>)}</>;
  }
  return <>{props.messages.map((item) => <div key={item.id} className={`table-row mode-messages ${props.activeMessage?.id === item.id ? "active" : ""} ${props.selectedMessageIds.has(item.id) ? "selected" : ""}`} onClick={() => props.onSelectMessage(item)}>
    <label className="checkbox-cell" onClick={(event) => event.stopPropagation()}><input type="checkbox" checked={props.selectedMessageIds.has(item.id)} onChange={(event) => toggleSet(item.id, event.target.checked, props.selectedMessageIds, props.setSelectedMessageIds)} /></label>
    <div className="cell-session mono" title={item.session_key}>{formatSessionKeyForTable(item.session_key)}</div>
    <div className="cell-seq mono">#{item.seq}</div>
    <div className="content-preview">{stripMarkdown(item.content)}</div>
    <div className="cell-time mono">{shortTs(item.ts)}</div>
    <div><span className={`role-pill ${roleClass(item.role)}`}>{item.role}</span></div>
    <div />
  </div>)}</>;
}

function DetailPane(props: {
  viewMode: ViewMode;
  activeSession: SessionRow | null;
  activeMessage: MessageRow | null;
  activeProactiveDetail: ProactiveTick | null;
  activeProactiveSteps: ProactiveStep[];
  plugin: PluginConfig | null;
  pluginState: PluginState | null;
  dispatch?: PluginDispatch;
  setProactiveSessionFilter(key: string): void;
}): React.ReactElement {
  if (props.viewMode.startsWith("plugin:") && props.plugin) {
    return <PluginDetail plugin={props.plugin} item={props.pluginState?.activeDetail ?? null} dispatch={props.dispatch} />;
  }
  if (props.viewMode === "proactive") {
    const item = props.activeProactiveDetail;
    if (!item) return <EmptyDetail text="点开 tick 后，这里会显示 proactive 执行详情和工具链。" />;
    return <div className="detail-wrap">
      <div className="detail-toolbar"><div><div className="detail-title">Tick 详情</div><div className="detail-subtext">{item.tick_id}</div></div></div>
      <button className="ghost" type="button" onClick={() => props.setProactiveSessionFilter(item.session_key)}>只看这个 session</button>
      <div className="detail-grid">
        {detailRow("session", <code>{item.session_key}</code>)}
        {detailRow("started", <code>{item.started_at}</code>)}
        {detailRow("result", <span className={`status-pill proactive-result-${proactiveResultLabel(item)}`}>{proactiveResultLabel(item)}</span>)}
        {detailRow("flow", <span className={`type-pill proactive-flow-${proactiveFlowLabel(item).toLowerCase()}`}>{proactiveFlowLabel(item)}</span>)}
      </div>
      {item.final_message && <div className="detail-block"><div className="detail-label">Final Message</div><div className="detail-content" dangerouslySetInnerHTML={{ __html: renderMarkdown(item.final_message) }} /></div>}
      <div className="detail-block"><div className="detail-label">Steps</div>{props.activeProactiveSteps.length ? props.activeProactiveSteps.map((step) => <div key={`${step.phase}-${step.step_index}`} className="tool-step"><div className="tool-step-head"><div className="tool-step-title"><span className="status-pill">step {step.step_index}</span><span className="type-pill">{step.tool_name}</span></div></div><JsonTreeBlock data={step.tool_args} /><div className="detail-content tool-result">{step.tool_result_text}</div></div>) : <div className="muted-text">没有记录到工具调用。</div>}</div>
    </div>;
  }
  if (props.activeMessage) {
    const message = props.activeMessage;
    return <div className="detail-wrap">
      <div className="detail-toolbar"><div><div className="detail-title">消息详情</div><div className="detail-subtext">{message.session_key} · #{message.seq}</div></div></div>
      <div className="detail-grid">
        {detailRow("role", <span className={`role-pill ${roleClass(message.role)}`}>{message.role}</span>)}
        {detailRow("time", <code>{message.ts}</code>)}
        {detailRow("id", <code>{message.id}</code>)}
      </div>
      <div className="detail-block"><div className="detail-label">Content</div><div className="detail-content" dangerouslySetInnerHTML={{ __html: renderMarkdown(message.content) }} /></div>
      <div className="detail-block"><div className="detail-label">Extra</div><JsonTreeBlock data={message.extra} /></div>
      <div className="detail-block"><div className="detail-label">Tool Chain</div><JsonTreeBlock data={message.tool_chain} /></div>
    </div>;
  }
  if (props.activeSession) {
    const session = props.activeSession;
    return <div className="detail-wrap">
      <div className="detail-toolbar"><div><div className="detail-title">Session 详情</div><div className="detail-subtext">{session.key}</div></div></div>
      <div className="detail-grid">
        {detailRow("messages", <code>{session.message_count}</code>)}
        {detailRow("updated", <code>{session.updated_at}</code>)}
        {detailRow("last_consolidated", <code>{session.last_consolidated}</code>)}
      </div>
      <div className="detail-block"><div className="detail-label">Metadata</div><JsonTreeBlock data={session.metadata} /></div>
    </div>;
  }
  return <EmptyDetail text="点开消息、session 或 memory 后，这里会显示完整内容、字段和 JSON 信息。" />;
}

function EmptyDetail(props: { text: string }): React.ReactElement {
  return <div className="detail-empty"><div className="detail-empty-title">详情</div><div className="detail-empty-text">{props.text}</div></div>;
}

function detailRow(label: string, value: React.ReactNode): React.ReactElement {
  return <div className="detail-row"><div className="detail-row-label">{label}</div><div className="detail-row-val">{value}</div></div>;
}

function JsonTreeBlock(props: { data: unknown }): React.ReactElement {
  const ref = useRef<HTMLDivElement>(null);
  const payload = JSON.stringify(props.data ?? null);

  useEffect(() => {
    if (!ref.current) return;
    ref.current.innerHTML = jvPlaceholder(props.data);
    attachJsonViewers(ref.current);
  }, [payload, props.data]);

  return <div ref={ref} />;
}

function toggleSet(id: string, checked: boolean, source: Set<string>, update: (value: Set<string>) => void): void {
  const next = new Set(source);
  if (checked) next.add(id);
  else next.delete(id);
  update(next);
}

function chatHistoryToEvents(items: MessageRow[]): ChatEventRow[] {
  const events: ChatEventRow[] = [];
  for (const item of items) {
    events.push(normalizeChatEvent({
      event: item.role === "assistant" ? "assistant_message" : "user_message",
      kind: item.role,
      label: item.role === "assistant" ? "Assistant" : "You",
      role: item.role,
      content: item.content,
      detail: item.content,
      seq: item.seq,
      metadata: item.extra,
      source: "history",
    }, item.session_key, item.ts));
  }
  return events;
}

function shouldKeepLiveEventAfterHistoryReload(event: ChatEventRow, history: ChatEventRow[]): boolean {
  if (event.source === "history") return false;
  if (event.source === "local" && event.kind === "user") {
    const text = String(event.content || event.detail || "").trim();
    return Boolean(text) && !history.some((item) => item.kind === "user" && String(item.content || item.detail || "").trim() === text);
  }
  if (event.source === "local") return event.kind === "error";
  return event.kind === "error";
}

function deriveChatTurns(events: ChatEventRow[]): ChatTurn[] {
  const turns: ChatTurn[] = [];
  for (const event of events) {
    let current = turns[turns.length - 1];
    if (event.event === "error") {
      if (!current) {
        current = { session_key: event.session_key };
        turns.push(current);
      }
      current.error = event;
      continue;
    }
    if (event.kind === "user") {
      current = { session_key: event.session_key, user: event };
      turns.push(current);
      continue;
    }
    if (!current) {
      current = { session_key: event.session_key };
      turns.push(current);
    }
    if (event.event === "done") {
      if (isLocalCommandAssistant(current.assistant)) {
        continue;
      }
      const steps = current.thinking?.steps ?? [];
      current.thinking = {
        status: "done",
        summary: `Completed · ${steps.length} step${steps.length === 1 ? "" : "s"}`,
        steps,
        technicalDetail: current.thinking?.technicalDetail,
        startedAt: current.thinking?.startedAt,
        updatedAt: event.ts ?? current.thinking?.updatedAt,
        expanded: current.thinking?.expanded,
      };
      continue;
    }
    if (event.kind === "assistant") {
      current.assistant = event;
      const textOnlyApprovalId = extractApprovalIdFromText(`${event.content || ""}\n${event.detail || ""}`);
      if (textOnlyApprovalId) {
        current.warning = {
          id: `${event.session_key}:pseudo-approval:${textOnlyApprovalId}`,
          session_key: event.session_key,
          event: "pseudo_approval",
          kind: "warning",
          label: "Approval not executable",
          detail: `The assistant mentioned approval ID ${textOnlyApprovalId}, but no framework approval was created. Ask the agent to call the tool, or use /biomed watch create ... to generate an approval card.`,
          created_at: event.created_at,
          ts: event.ts,
          source: "local",
        };
      }
      if (isLocalCommandAssistant(event)) {
        continue;
      }
      if (event.source !== "history" || current.thinking) {
        const steps = appendThinkingStep(current.thinking?.steps ?? [], event.pending ? "Preparing answer" : "Preparing final answer");
        current.thinking = {
          status: event.final ? "done" : "running",
          summary: event.pending ? "Preparing answer" : "Preparing final answer",
          steps,
          technicalDetail: current.thinking?.technicalDetail,
          startedAt: current.thinking?.startedAt,
          updatedAt: event.ts ?? current.thinking?.updatedAt,
          expanded: current.thinking?.expanded,
        };
      }
      continue;
    }
    if (isApprovalEvent(event)) {
      const nextApprovalId = extractApprovalId(event);
      const currentApprovalId = extractApprovalId(current.approval);
      if (nextApprovalId || !currentApprovalId) {
        current.approval = event;
      } else {
        current.warning = {
          id: `${event.session_key}:approval-missing-id:${event.call_id || event.id}`,
          session_key: event.session_key,
          event: "approval_missing_id",
          kind: "warning",
          label: "Approval not executable",
          detail: "A later approval event was missing its executable approval ID, so the existing approval card was kept.",
          created_at: event.created_at,
          ts: event.ts,
          source: "local",
        };
      }
      const steps = appendThinkingStep(current.thinking?.steps ?? [], "Waiting for confirmation");
      current.thinking = {
        status: "done",
        summary: "Waiting for confirmation",
        steps,
        technicalDetail: current.thinking?.technicalDetail,
        startedAt: current.thinking?.startedAt ?? event.ts,
        updatedAt: event.ts ?? current.thinking?.updatedAt,
        expanded: current.thinking?.expanded,
      };
      continue;
    }
    if (event.event === "assistant_message" || event.event === "turn_started") {
      const summary = event.summary || event.label || "Working";
      const steps = appendThinkingStep(current.thinking?.steps ?? [], humanThinkingStep(summary));
      current.thinking = {
        status: "running",
        summary: humanThinkingStep(summary),
        steps,
        technicalDetail: event.technical_detail ?? current.thinking?.technicalDetail,
        startedAt: event.ts ?? current.thinking?.startedAt,
        updatedAt: event.ts ?? current.thinking?.updatedAt,
        expanded: current.thinking?.expanded,
      };
      continue;
    }
    if (event.kind === "tool" || event.kind === "system") {
      const currentSteps = current.thinking?.steps ?? [];
      const rawStep = event.cockpit_phase
        ? `${event.cockpit_status || "running"} ${event.cockpit_phase}`
        : event.event === "tool_completed"
          ? ""
          : event.summary || event.label || event.detail || event.event;
      const nextStep = humanThinkingStep(rawStep);
      const steps = appendThinkingStep(currentSteps, nextStep);
      current.thinking = {
        status: "running",
        summary: nextStep || "Working",
        steps,
        technicalDetail: event.technical_detail ?? current.thinking?.technicalDetail,
        startedAt: current.thinking?.startedAt ?? event.ts,
        updatedAt: event.ts ?? current.thinking?.updatedAt,
        expanded: current.thinking?.expanded,
      };
      continue;
    }
  }
  return turns;
}

function isLocalCommandAssistant(event: ChatEventRow | null | undefined): boolean {
  const metadata = event?.metadata;
  if (!metadata) return false;
  const source = String(metadata.source ?? "");
  const commandAction = String((metadata.command as Record<string, unknown> | undefined)?.action ?? metadata.command_action ?? "");
  return source === "dashboard_chat_command" && Boolean(commandAction);
}

function isApprovalEvent(event: ChatEventRow): boolean {
  if (event.event === "tool_approval_required" || event.kind === "approval") {
    return true;
  }
  return event.status === "approval_required" && Boolean(extractApprovalId(event));
}

function appendThinkingStep(steps: string[], rawStep: string): string[] {
  const step = humanThinkingStep(rawStep);
  if (!step) return steps;
  if (steps.includes(step)) return steps;
  const next = [...steps, step];
  return next.slice(Math.max(0, next.length - 12));
}

function humanThinkingStep(raw: unknown): string {
  const text = String(raw ?? "").trim();
  const normalized = text.toLowerCase();
  if (!text) return "";
  if (normalized.includes("failed")) return "Run needs recovery";
  if (normalized.includes("planning")) return "Planning the evidence run";
  if (normalized.includes("retrieval")) return "Searching literature";
  if (normalized.includes("full-text")) return "Inspecting full text";
  if (normalized.includes("revision")) return "Revising unsupported claims";
  if (normalized.includes("packet")) return "Preparing evidence packet";
  if (normalized.includes("review")) return "Preparing Run Evidence Review";
  if (normalized.includes("export-ready")) return "Preparing export actions";
  if (normalized.includes("done")) return "Run completed";
  if (normalized.includes("provider") || normalized.includes("readiness")) return "Checking provider readiness";
  if (normalized.includes("plan") || normalized.includes("search planning")) return "Planning retrieval";
  if (normalized.includes("pubmed") || normalized.includes("literature") || normalized.includes("retrieval")) return "Searching literature";
  if (normalized.includes("extract")) return "Extracting evidence";
  if (normalized.includes("audit") || normalized.includes("verify") || normalized.includes("claim")) return "Auditing claims";
  if (normalized.includes("packet") || normalized.includes("provenance") || normalized.includes("packaging")) return "Preparing evidence packet";
  if (normalized.includes("confirm")) return "Waiting for confirmation";
  if (normalized.includes("draft") || normalized.includes("answer") || normalized.includes("response") || normalized.includes("writing")) return "Preparing answer";
  if (normalized.includes("started")) return "Starting workflow";
  if (normalized.includes("completed")) return "Completed";
  return text.length > 80 ? `${text.slice(0, 80).trim()}...` : text;
}

function chatTurnRunArtifacts(turn: ChatTurn): ChatRunArtifacts {
  const metadataArtifacts = extractArtifactsFromMetadata(turn.assistant?.metadata)
    ?? extractArtifactsFromMetadata(turn.user?.metadata);
  const text = [
    turn.assistant?.content,
    turn.assistant?.detail,
    turn.user?.content,
    turn.user?.detail,
  ].filter(Boolean).join("\n");
  const textRunId = extractRunId(text);
  const textWatchId = extractWatchId(text);
  const runId = metadataArtifacts?.run_id || textRunId;
  const watchId = metadataArtifacts?.watch_id || textWatchId;
  if (!runId && !watchId) return {};
  if (watchId && !runId) {
    return {
      watch_id: watchId,
      watch_url: `/api/biomed/watch/${encodeURIComponent(watchId)}`,
      watch_check_url: `/api/biomed/watch/${encodeURIComponent(watchId)}/check`,
      watch_drift_url: `/api/biomed/watch/${encodeURIComponent(watchId)}/drift`,
      ...(metadataArtifacts ?? {}),
    };
  }
  return {
    run_id: runId,
    review_url: `/api/biomed/answer-runs/${encodeURIComponent(runId)}/evidence-review`,
    packet_url: `/api/biomed/answer-runs/${encodeURIComponent(runId)}/evidence-review/packet`,
    trace_url: `/api/biomed/answer-runs/${encodeURIComponent(runId)}/trace`,
    provenance_url: `/api/biomed/answer-runs/${encodeURIComponent(runId)}/provenance`,
    pilot_report_markdown_url: `/api/biomed/export?run_id=${encodeURIComponent(runId)}&report_type=pilot&format=markdown`,
    pilot_report_json_url: `/api/biomed/export?run_id=${encodeURIComponent(runId)}&report_type=pilot&format=json`,
    argument_graph_url: `/api/biomed/answer-runs/${encodeURIComponent(runId)}/argument-graph`,
    evidence_graph_url: `/api/biomed/answer-runs/${encodeURIComponent(runId)}/evidence-graph`,
    ...(metadataArtifacts ?? {}),
  };
}

function extractArtifactsFromMetadata(metadata: Record<string, unknown> | undefined): ChatRunArtifacts | null {
  if (!metadata) return null;
  const direct = metadata.artifacts;
  if (direct && typeof direct === "object") {
    return direct as ChatRunArtifacts;
  }
  const command = metadata.command;
  if (command && typeof command === "object") {
    const commandArtifacts = (command as Record<string, unknown>).artifacts;
    if (commandArtifacts && typeof commandArtifacts === "object") {
      return commandArtifacts as ChatRunArtifacts;
    }
    const args = (command as Record<string, unknown>).arguments;
    if (args && typeof args === "object") {
      const runId = String((args as Record<string, unknown>).run_id || "").trim();
      if (runId) return { run_id: runId };
      const watchId = String((args as Record<string, unknown>).watch_id || "").trim();
      if (watchId) return { watch_id: watchId };
    }
  }
  const runId = String(metadata.run_id || "").trim();
  if (runId) return { run_id: runId };
  const watchId = String(metadata.watch_id || "").trim();
  if (watchId) return { watch_id: watchId };
  for (const urlKey of ["review_url", "packet_url", "trace_url", "provenance_url"]) {
    const value = String(metadata[urlKey] || "").trim();
    const runFromUrl = extractRunId(value);
    if (runFromUrl) return { run_id: runFromUrl };
  }
  return null;
}

function extractTurnApprovalId(turn: ChatTurn): string {
  return extractApprovalId(turn.approval);
}

function extractApprovalId(event: Partial<ChatEventRow> | null | undefined): string {
  if (!event) return "";
  const direct = stringFromUnknown(event.approval_id);
  if (direct) return direct;
  const confirmation = event.confirmation;
  if (confirmation && typeof confirmation === "object") {
    const confirmationId = stringFromUnknown((confirmation as Record<string, unknown>).approval_id);
    if (confirmationId) return confirmationId;
  }
  const metadata = event.metadata;
  if (metadata && typeof metadata === "object") {
    const metadataId = stringFromUnknown((metadata as Record<string, unknown>).approval_id);
    if (metadataId) return metadataId;
  }
  const finalArguments = event.final_arguments;
  if (finalArguments && typeof finalArguments === "object") {
    const finalApprovalId = stringFromUnknown((finalArguments as Record<string, unknown>).approval_id);
    if (finalApprovalId) return finalApprovalId;
  }
  return "";
}

function extractApprovalIdFromText(text: string): string {
  const match = String(text || "").match(/\bApproval ID:\s*`?([A-Za-z0-9_-]{8,64})`?/i)
    || String(text || "").match(/\bapproval ID\s*`?([A-Za-z0-9_-]{8,64})`?/i);
  return match?.[1] ?? "";
}

function extractRunId(text: string): string {
  const match = String(text || "").match(/\bbiomed-run-[A-Za-z0-9_-]+\b/);
  return match?.[0] ?? "";
}

function extractWatchId(text: string): string {
  const match = String(text || "").match(/\bwatch-[A-Za-z0-9_-]+\b/);
  return match?.[0] ?? "";
}

function arrayFromUnknown(value: unknown): Record<string, unknown>[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object");
}

function recordFromUnknown(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function nestedString(source: Record<string, unknown>, ...path: string[]): string {
  let current: unknown = source;
  for (const key of path) {
    current = recordFromUnknown(current)[key];
  }
  return stringFromUnknown(current);
}

function countNestedItems(source: Record<string, unknown>, keys: string[]): number | undefined {
  for (const key of keys) {
    const value = source[key];
    if (Array.isArray(value)) return value.length;
  }
  return undefined;
}

function reviewClaims(review: Record<string, unknown>, packet: Record<string, unknown>): Record<string, unknown>[] {
  const candidates = [
    review.claims,
    review.claim_summaries,
    review.claim_reviews,
    recordFromUnknown(review.audit).claim_audits,
    packet.claims,
    packet.claim_summaries,
    packet.evidence_summary,
  ];
  for (const candidate of candidates) {
    const items = arrayFromUnknown(candidate);
    if (items.length) return items;
  }
  return [];
}

function claimEvidenceSummary(claim: Record<string, unknown>): string {
  const direct = stringFromUnknown(claim.verdict)
    || stringFromUnknown(claim.status)
    || stringFromUnknown(claim.support_level)
    || stringFromUnknown(claim.evidence_strength)
    || stringFromUnknown(claim.audit_status);
  if (direct) return direct;
  const evidenceIds = Array.isArray(claim.evidence_ids) ? claim.evidence_ids.length : 0;
  if (evidenceIds > 0) return `${evidenceIds} evidence item${evidenceIds === 1 ? "" : "s"}`;
  return "Evidence review item";
}

function artifactSummary(
  target: RunReviewDrawerState["target"],
  review: Record<string, unknown>,
  packet: Record<string, unknown>,
  trace: Record<string, unknown>,
  provenance: Record<string, unknown>,
): string {
  if (target === "packet") {
    const citations = countNestedItems(packet, ["citations", "papers", "evidence_summary"]);
    return citations === undefined
      ? "The evidence packet endpoint is available for this run."
      : `Packet loaded with ${citations} evidence or citation item${citations === 1 ? "" : "s"}.`;
  }
  if (target === "trace") {
    const steps = countNestedItems(trace, ["steps", "trace", "events"]);
    return steps === undefined
      ? "The trace endpoint is available for this run."
      : `Trace loaded with ${steps} captured step${steps === 1 ? "" : "s"}.`;
  }
  if (target === "provenance") {
    const nodes = countNestedItems(recordFromUnknown(provenance.graph), ["nodes", "entities"]) ?? countNestedItems(provenance, ["nodes", "entities"]);
    return nodes === undefined
      ? "The provenance endpoint is available for this run."
      : `Provenance loaded with ${nodes} graph item${nodes === 1 ? "" : "s"}.`;
  }
  const claims = reviewClaims(review, packet).length;
  return claims
    ? `Review loaded with ${claims} claim card${claims === 1 ? "" : "s"}.`
    : "The Run Evidence Review endpoint is available for this run.";
}

function stringFromUnknown(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "";
}

function numberFromUnknown(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() && Number.isFinite(Number(value))) return Number(value);
  return undefined;
}

function collectReviewWarnings(...items: Array<Record<string, unknown>>): string[] {
  const warnings: string[] = [];
  for (const item of items) {
    for (const key of ["warnings", "limitations", "caveats"]) {
      const value = item[key];
      if (Array.isArray(value)) {
        for (const warning of value) {
          const text = stringFromUnknown(warning);
          if (text && !warnings.includes(text)) warnings.push(text);
        }
      }
    }
    const error = item.error;
    const errorText = stringFromUnknown(error);
    if (errorText && !warnings.includes(errorText)) warnings.push(errorText);
  }
  return warnings;
}

function hasArtifactError(item: Record<string, unknown>): boolean {
  return Boolean(item.error);
}

function normalizeChatEvent(
  event: Partial<ChatEventRow> & { event: string },
  fallbackSessionKey: string,
  createdAt: string,
): ChatEventRow {
  const sessionKey = String(event.session_key || fallbackSessionKey);
  const kind = String(event.kind || event.event);
  const label = String(event.label || event.event);
  return {
    id: `${sessionKey}-${event.seq ?? createdAt}-${event.event}-${Math.random().toString(36).slice(2)}`,
    session_key: sessionKey,
    seq: typeof event.seq === "number" ? event.seq : undefined,
    event: event.event,
    kind,
    label,
    role: event.role,
    content: event.content,
    detail: event.detail ?? event.content ?? event.content_delta ?? event.thinking_delta,
    content_delta: event.content_delta,
    thinking_delta: event.thinking_delta,
    thinking: event.thinking,
    tool_name: event.tool_name,
    call_id: event.call_id,
    arguments: event.arguments,
    final_arguments: event.final_arguments,
    approval_id: event.approval_id,
    confirmation: event.confirmation,
    status: event.status,
    iteration: event.iteration,
    has_more: event.has_more,
    final: event.final,
    summary: event.summary,
    technical_detail: event.technical_detail,
    raw: event.raw,
    metadata: (event.metadata && typeof event.metadata === "object") ? event.metadata as Record<string, unknown> : undefined,
    cockpit_phase: typeof event.cockpit_phase === "string" ? event.cockpit_phase : undefined,
    cockpit_status: typeof event.cockpit_status === "string" ? event.cockpit_status : undefined,
    recovery: event.recovery && typeof event.recovery === "object" ? event.recovery as ChatEventRow["recovery"] : null,
    source: event.source,
    pending: event.pending,
    ts: event.ts,
    created_at: createdAt,
  };
}

function chatSessionTitle(session: SessionRow | null | undefined): string {
  const title = session ? String((session.metadata as ChatSessionMetadata | null | undefined)?.title ?? "").trim() : "";
  if (title) return title;
  return session?.key ? formatSessionKeyForTable(session.key) : "New chat";
}

function chatSessionSubtitle(session: SessionRow | null | undefined): string {
  if (!session) return "Conversation";
  const count = session.message_count || 0;
  return `${relativeTime(session.updated_at)} · ${count} message${count === 1 ? "" : "s"}`;
}

function commandPreviewProblem(preview: ChatCommandPreview): string {
  if (preview.errors.length) {
    return preview.errors.join("; ");
  }
  if (preview.missing_requirements.length) {
    return preview.missing_requirements
      .map((item) => `${item.label}: ${item.detail}`)
      .join(" ");
  }
  return "Command is not ready to send.";
}

function commandPreviewStatusLabel(preview: ChatCommandPreview): string {
  if (preview.can_send && preview.confirmation) return "Confirmation required";
  if (preview.can_send) return "Ready";
  if (preview.errors.some((item) => item.toLowerCase().includes("run id"))) return "Needs run ID";
  if (preview.errors.some((item) => item.toLowerCase().includes("confirmation"))) return "Confirmation required";
  if (preview.missing_requirements.length) return "Needs setup";
  if (preview.errors.length) return "Needs edits";
  return "Needs setup";
}

async function copySessionKey(value: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(value);
  } catch {
    return;
  }
}

function mergeChatEvent(current: ChatEventRow[], next: ChatEventRow): ChatEventRow[] {
  if (next.event === "assistant_delta") {
    const index = [...current].reverse().findIndex((item) => item.session_key === next.session_key && item.kind === "assistant" && item.pending);
    if (index >= 0) {
      const actualIndex = current.length - 1 - index;
      const target = current[actualIndex];
      const mergedContent = `${target.content ?? ""}${next.content_delta ?? ""}`;
      const mergedThinking = `${target.thinking ?? ""}${next.thinking_delta ?? ""}`;
      const merged: ChatEventRow = {
        ...target,
        content: mergedContent,
        detail: mergedContent || target.detail,
        thinking: mergedThinking || target.thinking,
        cockpit_phase: next.cockpit_phase ?? target.cockpit_phase,
        cockpit_status: next.cockpit_status ?? target.cockpit_status,
        recovery: next.recovery ?? target.recovery,
        final: next.has_more === false,
        pending: next.has_more !== false,
        ts: next.ts ?? target.ts,
      };
      return [...current.slice(0, actualIndex), merged, ...current.slice(actualIndex + 1)];
    }
    return [
      ...current,
      {
        ...next,
        kind: "assistant",
        label: "Assistant",
        role: "assistant",
        content: next.content_delta ?? "",
        detail: next.content_delta ?? "",
        thinking: next.thinking_delta,
        pending: true,
        final: false,
      },
    ];
  }
  if (next.event === "assistant_message") {
    const targetIndex = [...current].reverse().findIndex((item) => item.session_key === next.session_key && item.kind === "assistant" && item.pending);
    if (targetIndex >= 0) {
      const actualIndex = current.length - 1 - targetIndex;
      const target = current[actualIndex];
      const merged: ChatEventRow = {
        ...target,
        event: "assistant_message",
        kind: "assistant",
        label: "Assistant",
        role: "assistant",
        content: next.content ?? target.content,
        detail: next.content ?? target.detail ?? target.content,
        thinking: next.thinking ?? target.thinking,
        metadata: next.metadata ?? target.metadata,
        cockpit_phase: next.cockpit_phase ?? target.cockpit_phase,
        cockpit_status: next.cockpit_status ?? target.cockpit_status,
        recovery: next.recovery ?? target.recovery,
        final: true,
        pending: false,
        ts: next.ts ?? target.ts,
      };
      return [...current.slice(0, actualIndex), merged, ...current.slice(actualIndex + 1)];
    }
  }
  return [...current, next];
}

function parseSseChunk(chunk: string): { event: string; data: Record<string, unknown> } | null {
  let event = "";
  const dataLines: string[] = [];
  for (const line of chunk.split("\n")) {
    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trim());
    }
  }
  if (!event || !dataLines.length) return null;
  try {
    return { event, data: JSON.parse(dataLines.join("\n")) as Record<string, unknown> };
  } catch {
    return null;
  }
}

function chatSeqStorageKey(sessionKey: string): string {
  return `akashic.dashboard.chat.seq.${sessionKey}`;
}

function getStoredChatSeq(sessionKey: string): number {
  try {
    const value = Number(window.sessionStorage.getItem(chatSeqStorageKey(sessionKey)) || "0");
    return Number.isFinite(value) && value > 0 ? Math.floor(value) : 0;
  } catch {
    return 0;
  }
}

function updateStoredChatSeq(sessionKey: string, data: Record<string, unknown>, opts?: { authoritative?: boolean }): void {
  const candidates = [data.seq, data.latest_seq];
  const next = Math.max(
    0,
    ...candidates
      .map((value) => (typeof value === "number" ? value : Number(value)))
      .filter((value) => Number.isFinite(value)),
  );
  if (next <= 0) return;
  try {
    const current = getStoredChatSeq(sessionKey);
    if (opts?.authoritative || next > current) {
      window.sessionStorage.setItem(chatSeqStorageKey(sessionKey), String(next));
    }
  } catch {
    return;
  }
}

function latestChatEventSeq(events: ChatEventRow[], sessionKey: string): number {
  return Math.max(
    0,
    ...events
      .filter((event) => event.session_key === sessionKey && event.source !== "history")
      .map((event) => typeof event.seq === "number" ? event.seq : 0)
      .filter((value) => Number.isFinite(value)),
  );
}

function presentChatEvent(event: string, data: Record<string, unknown>): {
  summary: string;
  technicalDetail?: string;
} {
  const toolName = typeof data.tool_name === "string" ? data.tool_name : "";
  const label = String(data.label ?? "");
  const detail = String(data.detail ?? data.message ?? "");
  let summary = label || detail || event;
  if (event === "user_message_accepted") {
    summary = "Message received";
  } else if (event === "turn_started") {
    summary = "Agent started the review";
  } else if (event === "tool_started") {
    summary = toolProgressSummary(toolName, "started");
  } else if (event === "tool_completed") {
    summary = toolProgressSummary(toolName, String(data.status ?? "completed"));
  } else if (event === "step") {
    summary = stepProgressSummary(label || detail);
  } else if (event === "error") {
    summary = detail || "Something went wrong";
  }
  return {
    summary,
    technicalDetail: compactChatTechnicalDetail(event, data),
  };
}

function toolProgressSummary(toolName: string, status: string): string {
  const done = status === "success" || status === "completed" || status === "done";
  const prefix = done ? "Completed" : "Running";
  const normalized = toolName.toLowerCase();
  if (normalized.includes("workflow") || normalized.includes("tool_chain")) {
    return `${prefix} the evidence review workflow`;
  }
  if (normalized.includes("plan_biomedical_search") || normalized.includes("plan")) {
    return `${prefix} search planning`;
  }
  if (normalized.includes("search_literature") || normalized.includes("pubmed") || normalized.includes("literature")) {
    return `${prefix} literature retrieval`;
  }
  if (normalized.includes("extract")) {
    return `${prefix} evidence extraction`;
  }
  if (normalized.includes("audit") || normalized.includes("verify")) {
    return `${prefix} citation and claim checks`;
  }
  if (normalized.includes("provenance") || normalized.includes("evidence_packet")) {
    return `${prefix} evidence packaging`;
  }
  if (toolName) {
    return `${prefix} ${humanizeToolName(toolName)}`;
  }
  return done ? "Step completed" : "Working on the request";
}

function stepProgressSummary(value: string): string {
  const normalized = value.toLowerCase();
  if (normalized.includes("assistant response ready")) {
    return "Drafting the response";
  }
  if (normalized.includes("tools called")) {
    return "Review workflow is progressing";
  }
  if (normalized.includes("accepted")) {
    return "Request accepted";
  }
  if (normalized.includes("started")) {
    return "Agent started the review";
  }
  return value || "Review workflow is progressing";
}

function humanizeToolName(value: string): string {
  return value
    .replace(/^mcp__[^.]+\./, "")
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function compactChatTechnicalDetail(event: string, data: Record<string, unknown>): string | undefined {
  const details: Record<string, unknown> = { event };
  for (const key of ["tool_name", "status", "iteration", "call_id", "detail", "label", "arguments", "final_arguments", "has_more"]) {
    if (data[key] !== undefined && data[key] !== "") {
      details[key] = data[key];
    }
  }
  if (Object.keys(details).length <= 1) return undefined;
  const serialized = JSON.stringify(details, null, 2);
  return serialized.length > 1400 ? `${serialized.slice(0, 1400)}\n...` : serialized;
}

function chatNetworkErrorMessage(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error || "");
  if (message.toLowerCase().includes("failed to fetch")) {
    return "Dashboard backend is unreachable. Check that the full runtime is running at the current address, then retry.";
  }
  return message || "Dashboard backend is unreachable. Check the runtime and retry.";
}

function isAbortError(error: unknown): boolean {
  if (error instanceof DOMException && error.name === "AbortError") return true;
  const message = error instanceof Error ? error.message : String(error || "");
  return /abort|aborted/i.test(message);
}

function errorWithCause(message: string, cause: unknown): Error {
  const error = new Error(message) as Error & { cause?: unknown };
  error.cause = cause;
  return error;
}

function handleChatSsePayload(
  event: string,
  data: Record<string, unknown>,
  ctx: {
    appendChatEvent(event: Partial<ChatEventRow> & { event: string }): void;
    setChatSending(value: boolean): void;
    setChatLiveEvent(value: string): void;
  },
): void {
  if (event === "connected") {
    return;
  }
  const seq = readChatSeq(data);
  const presentation = presentChatEvent(event, data);
  const cockpit = {
    cockpit_phase: typeof data.cockpit_phase === "string" ? data.cockpit_phase : undefined,
    cockpit_status: typeof data.cockpit_status === "string" ? data.cockpit_status : undefined,
    recovery: data.recovery && typeof data.recovery === "object" ? data.recovery as ChatEventRow["recovery"] : null,
  };
  if (event === "user_message_accepted") {
    ctx.setChatLiveEvent("Message received");
    return;
  }
  if (event === "turn_started") {
    ctx.appendChatEvent({
      event,
      seq,
      kind: "system",
      label: String(data.label ?? "Agent started"),
      detail: String(data.detail ?? ""),
      summary: presentation.summary,
      technical_detail: presentation.technicalDetail,
      raw: data,
      ...cockpit,
      session_key: String(data.session_key ?? ""),
      source: "live",
    });
    ctx.setChatLiveEvent(presentation.summary);
    return;
  }
  if (event === "assistant_delta") {
    ctx.appendChatEvent({
      event,
      seq,
      kind: "assistant",
      label: "Assistant streaming",
      detail: String(data.content_delta ?? data.thinking_delta ?? ""),
      ...cockpit,
      content_delta: typeof data.content_delta === "string" ? data.content_delta : undefined,
      thinking_delta: typeof data.thinking_delta === "string" ? data.thinking_delta : undefined,
      session_key: String(data.session_key ?? ""),
      pending: true,
      source: "live",
    });
    ctx.setChatLiveEvent("Writing the response");
    return;
  }
  if (event === "assistant_message") {
    ctx.appendChatEvent({
      event,
      seq,
      kind: "assistant",
      label: "Assistant",
      detail: String(data.content ?? ""),
      ...cockpit,
      session_key: String(data.session_key ?? ""),
      content: String(data.content ?? ""),
      thinking: typeof data.thinking === "string" ? data.thinking : undefined,
      metadata: recordFromUnknown(data.metadata),
      final: true,
      pending: false,
      source: "live",
    });
    ctx.setChatSending(false);
    ctx.setChatLiveEvent("");
    return;
  }
  if (event === "tool_started") {
    ctx.appendChatEvent({
      event,
      seq,
      kind: "tool",
      label: String(data.label ?? data.tool_name ?? "Tool started"),
      detail: String(data.tool_name ?? ""),
      summary: presentation.summary,
      technical_detail: presentation.technicalDetail,
      raw: data,
      ...cockpit,
      session_key: String(data.session_key ?? ""),
      tool_name: typeof data.tool_name === "string" ? data.tool_name : undefined,
      call_id: typeof data.call_id === "string" ? data.call_id : undefined,
      arguments: data.arguments,
      iteration: typeof data.iteration === "number" ? data.iteration : undefined,
      source: "live",
    });
    ctx.setChatLiveEvent(presentation.summary);
    return;
  }
  if (event === "tool_completed") {
    ctx.appendChatEvent({
      event,
      seq,
      kind: "tool",
      label: String(data.label ?? data.tool_name ?? "Tool completed"),
      detail: String(data.detail ?? ""),
      summary: presentation.summary,
      technical_detail: presentation.technicalDetail,
      raw: data,
      ...cockpit,
      session_key: String(data.session_key ?? ""),
      tool_name: typeof data.tool_name === "string" ? data.tool_name : undefined,
      call_id: typeof data.call_id === "string" ? data.call_id : undefined,
      arguments: data.arguments,
      final_arguments: data.final_arguments,
      status: typeof data.status === "string" ? data.status : undefined,
      iteration: typeof data.iteration === "number" ? data.iteration : undefined,
      metadata: recordFromUnknown(data.metadata),
      source: "live",
    });
    ctx.setChatLiveEvent(presentation.summary);
    return;
  }
  if (event === "step") {
    ctx.appendChatEvent({
      event,
      seq,
      kind: "system",
      label: String(data.label ?? "Assistant response ready"),
      detail: String(data.detail ?? ""),
      summary: presentation.summary,
      technical_detail: presentation.technicalDetail,
      raw: data,
      ...cockpit,
      session_key: String(data.session_key ?? ""),
      iteration: typeof data.iteration === "number" ? data.iteration : undefined,
      has_more: typeof data.has_more === "boolean" ? data.has_more : undefined,
      source: "live",
    });
    ctx.setChatLiveEvent(presentation.summary);
    if (data.has_more === false) {
      ctx.setChatSending(false);
    }
    return;
  }
  if (event === "done") {
    ctx.appendChatEvent({
      event,
      seq,
      kind: "system",
      label: "Completed",
      summary: "Completed",
      ...cockpit,
      session_key: String(data.session_key ?? ""),
      source: "live",
    });
    ctx.setChatSending(false);
    ctx.setChatLiveEvent("");
    return;
  }
  if (event === "error") {
    ctx.appendChatEvent({
      event,
      seq,
      kind: "error",
      label: String(data.label ?? "Error"),
      detail: String(data.detail ?? data.message ?? "Error"),
      summary: presentation.summary,
      technical_detail: presentation.technicalDetail,
      raw: data,
      ...cockpit,
      session_key: String(data.session_key ?? ""),
      source: "live",
    });
    ctx.setChatSending(false);
    ctx.setChatLiveEvent("");
    return;
  }
  ctx.appendChatEvent({
    event,
    seq,
    kind: String(data.kind ?? "system"),
    label: String(data.label ?? event),
    detail: String(data.detail ?? data.content_delta ?? data.message ?? ""),
    summary: presentation.summary,
    technical_detail: presentation.technicalDetail,
    raw: data,
    ...cockpit,
    content_delta: typeof data.content_delta === "string" ? data.content_delta : undefined,
    thinking_delta: typeof data.thinking_delta === "string" ? data.thinking_delta : undefined,
    tool_name: typeof data.tool_name === "string" ? data.tool_name : undefined,
    call_id: typeof data.call_id === "string" ? data.call_id : undefined,
    arguments: data.arguments,
    final_arguments: data.final_arguments,
    approval_id: typeof data.approval_id === "string" ? data.approval_id : undefined,
    confirmation: data.confirmation,
    status: typeof data.status === "string" ? data.status : undefined,
    iteration: typeof data.iteration === "number" ? data.iteration : undefined,
    has_more: typeof data.has_more === "boolean" ? data.has_more : undefined,
    source: "live",
    session_key: String(data.session_key ?? ""),
  });
}

function readChatSeq(data: Record<string, unknown>): number | undefined {
  const raw = data.seq;
  const value = typeof raw === "number" ? raw : Number(raw);
  return Number.isFinite(value) && value > 0 ? Math.floor(value) : undefined;
}

function gridTemplate(columns: DashboardColumn[]): string {
  return columns.map((col) => col.flex ? "1fr" : col.width ? `${col.width}px` : "auto").join(" ");
}

function formatPluginCell(plugin: PluginConfig, column: DashboardColumn, item: Record<string, unknown>): string {
  const value = item[column.key];
  const formatter = plugin.formatters?.[column.fmt || ""] ?? (window as Window & { AkashicDashboard?: { _formatters: Record<string, (value: unknown, item?: Record<string, unknown>) => string> } }).AkashicDashboard?._formatters[column.fmt || "text"];
  return formatter ? formatter(value, item) : String(value ?? "");
}

function columnCellClass(column: DashboardColumn): string {
  const classes = [column.cellClass ?? ""];
  if (column.align === "right") classes.push("align-right");
  return classes.filter(Boolean).join(" ");
}

function tableMeta(viewMode: ViewMode, totalMessages: number, proactiveTotal: number, plugin: PluginConfig | null, pluginState: PluginState | null, proactiveSessionFilter: string): string {
  if (plugin && pluginState) return plugin.countTitle ? plugin.countTitle(pluginState.total) : `共 ${pluginState.total} 条`;
  if (viewMode === "proactive") return proactiveSessionFilter ? `共 ${proactiveTotal} 条 tick · session: ${proactiveSessionFilter}` : `共 ${proactiveTotal} 条 tick`;
  return `共 ${totalMessages} 条`;
}

function totalSessionMessages(sessions: SessionRow[]): number {
  return sessions.reduce((sum, session) => sum + (session.message_count || 0), 0);
}

function proactiveSectionCount(section: string, overview: ProactiveOverview | null): number {
  if (!overview) return 0;
  if (section === "all") return overview.counts.tick_logs ?? 0;
  if (section === "drift" || section === "proactive") return overview.flow_counts[section] ?? 0;
  return overview.result_counts[section] ?? 0;
}

function viewLabel(viewMode: ViewMode, plugin: PluginConfig | null): string {
  if (plugin) return plugin.viewLabel || plugin.label;
  if (viewMode === "chat") return "chat";
  if (viewMode === "proactive") return "proactive";
  return "messages";
}

createRoot(document.getElementById("root") as HTMLElement).render(<App />);
