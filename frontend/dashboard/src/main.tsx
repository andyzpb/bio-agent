import React, { useCallback, useEffect, useEffectEvent, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
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
  ChatStatus,
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
  const chatAbortRef = useRef<AbortController | null>(null);
  const chatStreamRef = useRef<ReadableStreamDefaultReader<Uint8Array> | null>(null);
  const chatSeqRef = useRef<Record<string, number>>({});
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

  const channels = useMemo(() => Array.from(new Set(sessions.map((session) => session.key.split(":")[0]).filter(Boolean))), [sessions]);

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

  const loadChatHistory = useCallback(async (sessionKey: string) => {
    const params = new URLSearchParams();
    params.set("session_key", sessionKey);
    params.set("page_size", "120");
    const payload = await api<PageResult<MessageRow> & { session_key?: string }>(`/api/dashboard/chat/history?${params.toString()}`);
    const history = chatHistoryToEvents(payload.items ?? []);
    setChatEvents((current) => [
      ...history,
      ...current.filter((event) => event.session_key === sessionKey && event.source !== "history"),
    ]);
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
    const sinceSeq = getStoredChatSeq(sessionKey);
    chatSeqRef.current[sessionKey] = sinceSeq;
    if (sinceSeq > 0) params.set("since_seq", String(sinceSeq));
    const response = await fetch(`/api/dashboard/chat/stream?${params.toString()}`, {
      signal: controller.signal,
      headers: { Accept: "text/event-stream" },
    });
    if (!response.ok || !response.body) {
      const payload = await response.json().catch(() => ({})) as { detail?: string };
      throw new Error(payload.detail || `请求失败: ${response.status}`);
    }
    const reader = response.body.getReader();
    chatStreamRef.current = reader;
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
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
    setChatInput("");
    setChatSending(true);
    appendChatEvent({
      event: "user",
      kind: "user",
      label: "You",
      content,
      detail: content,
      session_key: chatSessionKey,
      source: "local",
    });
    try {
      await api("/api/dashboard/chat/messages", {
        method: "POST",
        body: JSON.stringify({ content, session_key: chatSessionKey }),
      });
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
  }, [appendChatEvent, chatInput, chatSending, chatSessionKey]);

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
    });
  }, [loadChatStatus, loadMessages, loadProactiveOverview, loadSessions, run]);

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
      if (exc instanceof DOMException && exc.name === "AbortError") return;
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
                ? (currentPlugin.countTitle ? currentPlugin.countTitle(currentPluginState.total) : `${currentPluginState.total} 条记录`)
                : `${sessions.length} 个会话`}
            </div>
          </div>
          <div className="filters-stack">
            <label className="search search-small">
              <span>⌕</span>
              <input type="text" placeholder="过滤 session" value={sessionSearch} onChange={(event) => setSessionSearch(event.target.value.trim())} />
            </label>
            <select value={sessionChannel} onChange={(event) => setSessionChannel(event.target.value)}>
              <option value="">全部 channel</option>
              {channels.map((channel) => <option key={channel} value={channel}>{channel}</option>)}
            </select>
          </div>
          <nav className="explorer-nav">
            <NavGroup label="Chat" count={dashboardSessions.length} active={viewMode === "chat"} open={!!navOpen.chat} onToggle={() => toggleNav("chat")}>
              <button className={`all-messages-row ${viewMode === "chat" && chatSessionKey === "dashboard:default" ? "active" : ""}`} type="button" onClick={() => {
                setChatSessionKey("dashboard:default");
                selectView("chat");
              }}>
                <span>dashboard:default</span><strong>{chatStatus?.enabled ? "on" : "off"}</strong>
              </button>
              <div className="session-list">
                {dashboardSessions.filter((session) => session.key !== "dashboard:default").map((session) => (
                  <button key={session.key} className={`session-item ${chatSessionKey === session.key ? "active" : ""}`} type="button" onClick={() => {
                    setChatSessionKey(session.key);
                    setChatEvents([]);
                    setChatLiveEvent("");
                    selectView("chat");
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
            <NavGroup label="Sessions" count={totalMessages || totalSessionMessages(sessions)} active={viewMode === "sessions"} open={!!navOpen.sessions} onToggle={() => toggleNav("sessions")}>
              <button className={`all-messages-row ${viewMode === "sessions" && !activeSessionKey ? "active" : ""}`} type="button" onClick={() => {
                setActiveSessionKey(null);
                setActiveSession(null);
                setActiveMessage(null);
                setMessagePage(1);
                selectView("sessions");
              }}>
                <span>全部消息</span><strong>{sessions.length}</strong>
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
            sessionKey={chatSessionKey}
            setSessionKey={(value) => {
              setChatSessionKey(value);
              setChatEvents([]);
              setChatLiveEvent("");
            }}
            connected={chatConnected}
            events={chatEvents}
            input={chatInput}
            setInput={setChatInput}
            sending={chatSending}
            liveEvent={chatLiveEvent}
            onSend={() => void run(sendChatMessage)}
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
      {error && <div className="modal-backdrop" onClick={() => setError(null)}><div className="modal"><div className="modal-title">请求失败</div><p>{error}</p><div className="modal-actions"><button className="primary" type="button" onClick={() => setError(null)}>关闭</button></div></div></div>}
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
  sessionKey: string;
  setSessionKey(value: string): void;
  connected: boolean;
  events: ChatEventRow[];
  input: string;
  setInput(value: string): void;
  sending: boolean;
  liveEvent: string;
  onSend(): void;
  onOpenSession(): void;
}): React.ReactElement {
  const disabled = !props.status?.enabled;
  const streamRef = useRef<HTMLDivElement>(null);
  const latestContentKey = props.events
    .map((event) => `${event.id}:${event.content ?? ""}:${event.detail ?? ""}`)
    .join("|");

  useEffect(() => {
    if (disabled) return;
    const el = streamRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [disabled, latestContentKey, props.liveEvent, props.sending]);

  return (
    <section className="chat-pane">
      <header className="chat-head">
        <div>
          <div className="chat-title">Dashboard Chat</div>
          <div className="chat-subtitle">
            <span className={`chat-dot ${props.connected && !disabled ? "on" : ""}`} />
            <code>{props.sessionKey}</code>
          </div>
        </div>
        <div className="chat-head-actions">
          <label className="chat-session-input">
            <span>session</span>
            <input
              type="text"
              value={props.sessionKey}
              onChange={(event) => props.setSessionKey(event.target.value.trim() || "dashboard:default")}
              disabled={props.sending}
            />
          </label>
          <button className="ghost" type="button" onClick={props.onOpenSession}>查看 session</button>
        </div>
      </header>
      {disabled ? (
        <div className="chat-disabled">
          <div className="detail-empty-title">完整 runtime 未启用</div>
          <div className="detail-empty-text">{props.status?.reason || "Dashboard Chat requires python main.py."}</div>
        </div>
      ) : (
        <>
          <div className="chat-stream" ref={streamRef}>
            {props.events.length ? props.events.map((event) => <ChatEventItem
              key={event.id}
              event={event}
            />) : (
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
              <div className="chat-event chat-event-running">
                <span className="status-pill">running</span>
                <span>{props.liveEvent || "等待 agent 回复"}</span>
              </div>
            )}
          </div>
          <form className="chat-composer" onSubmit={(event) => { event.preventDefault(); props.onSend(); }}>
            <textarea
              value={props.input}
              placeholder="Send a message to the agent..."
              onChange={(event) => props.setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  props.onSend();
                }
              }}
              disabled={props.sending}
            />
            <button className="primary" type="submit" disabled={props.sending || !props.input.trim()}>
              {props.sending ? "发送中" : "发送"}
            </button>
          </form>
        </>
      )}
    </section>
  );
}

function ChatEventItem(props: {
  event: ChatEventRow;
}): React.ReactElement {
  const event = props.event;
  if (event.kind === "user") {
    return <div className="chat-message user"><div className="chat-bubble">{event.content || event.detail}</div></div>;
  }
  if (event.kind === "assistant" && (event.content || event.detail || event.pending)) {
    const content = event.content || event.detail || "";
    return <div className={`chat-message assistant${event.pending ? " pending" : ""}`}><div className="chat-bubble" dangerouslySetInnerHTML={{ __html: renderMarkdown(content || " ") }} /></div>;
  }
  if (event.event === "error") {
    return <div className="chat-event error"><span className="status-pill proactive-result-busy">error</span><span>{event.detail}</span></div>;
  }
  if (event.event === "user_message_accepted") {
    return <div className="chat-event"><span className="status-pill">accepted</span><span>{event.detail || "Message accepted"}</span></div>;
  }
  if (event.kind === "tool") {
    const status = event.status || (event.event === "tool_started" ? "started" : "tool");
    return <div className="chat-event chat-tool-event"><span className="status-pill">{status}</span><span>{event.tool_name || event.label}</span>{event.detail && <small>{event.detail}</small>}</div>;
  }
  return <div className="chat-event"><span className="status-pill">{event.kind}</span><span>{event.label}</span>{event.detail && <small>{event.detail}</small>}</div>;
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
      source: "history",
    }, item.session_key, item.ts));
  }
  return events;
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
    status: event.status,
    iteration: event.iteration,
    has_more: event.has_more,
    final: event.final,
    source: event.source,
    pending: event.pending,
    ts: event.ts,
    created_at: createdAt,
  };
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
  if (event === "user_message_accepted") {
    ctx.appendChatEvent({
      event,
      seq,
      kind: "system",
      label: "Message accepted",
      detail: String(data.detail ?? data.content_preview ?? "Message accepted"),
      session_key: String(data.session_key ?? ""),
      source: "live",
    });
    return;
  }
  if (event === "turn_started") {
    ctx.appendChatEvent({
      event,
      seq,
      kind: "system",
      label: String(data.label ?? "Agent started"),
      detail: String(data.detail ?? ""),
      session_key: String(data.session_key ?? ""),
      source: "live",
    });
    ctx.setChatLiveEvent(String(data.label ?? data.detail ?? "Agent started"));
    return;
  }
  if (event === "assistant_delta") {
    ctx.appendChatEvent({
      event,
      seq,
      kind: "assistant",
      label: "Assistant streaming",
      detail: String(data.content_delta ?? data.thinking_delta ?? ""),
      content_delta: typeof data.content_delta === "string" ? data.content_delta : undefined,
      thinking_delta: typeof data.thinking_delta === "string" ? data.thinking_delta : undefined,
      session_key: String(data.session_key ?? ""),
      pending: true,
      source: "live",
    });
    ctx.setChatLiveEvent(String(data.content_delta ?? data.thinking_delta ?? "Assistant streaming"));
    return;
  }
  if (event === "assistant_message") {
    ctx.appendChatEvent({
      event,
      seq,
      kind: "assistant",
      label: "Assistant",
      detail: String(data.content ?? ""),
      session_key: String(data.session_key ?? ""),
      content: String(data.content ?? ""),
      thinking: typeof data.thinking === "string" ? data.thinking : undefined,
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
      session_key: String(data.session_key ?? ""),
      tool_name: typeof data.tool_name === "string" ? data.tool_name : undefined,
      call_id: typeof data.call_id === "string" ? data.call_id : undefined,
      arguments: data.arguments,
      iteration: typeof data.iteration === "number" ? data.iteration : undefined,
      source: "live",
    });
    ctx.setChatLiveEvent(String(data.label ?? data.tool_name ?? "Tool started"));
    return;
  }
  if (event === "tool_completed") {
    ctx.appendChatEvent({
      event,
      seq,
      kind: "tool",
      label: String(data.label ?? data.tool_name ?? "Tool completed"),
      detail: String(data.detail ?? ""),
      session_key: String(data.session_key ?? ""),
      tool_name: typeof data.tool_name === "string" ? data.tool_name : undefined,
      call_id: typeof data.call_id === "string" ? data.call_id : undefined,
      arguments: data.arguments,
      final_arguments: data.final_arguments,
      status: typeof data.status === "string" ? data.status : undefined,
      iteration: typeof data.iteration === "number" ? data.iteration : undefined,
      source: "live",
    });
    ctx.setChatLiveEvent(String(data.label ?? data.tool_name ?? "Tool completed"));
    return;
  }
  if (event === "step") {
    ctx.appendChatEvent({
      event,
      seq,
      kind: "system",
      label: String(data.label ?? "Assistant response ready"),
      detail: String(data.detail ?? ""),
      session_key: String(data.session_key ?? ""),
      iteration: typeof data.iteration === "number" ? data.iteration : undefined,
      has_more: typeof data.has_more === "boolean" ? data.has_more : undefined,
      source: "live",
    });
    ctx.setChatLiveEvent(String(data.label ?? data.kind ?? "running"));
    if (data.has_more === false) {
      ctx.setChatSending(false);
    }
    return;
  }
  if (event === "done") {
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
    content_delta: typeof data.content_delta === "string" ? data.content_delta : undefined,
    thinking_delta: typeof data.thinking_delta === "string" ? data.thinking_delta : undefined,
    tool_name: typeof data.tool_name === "string" ? data.tool_name : undefined,
    call_id: typeof data.call_id === "string" ? data.call_id : undefined,
    arguments: data.arguments,
    final_arguments: data.final_arguments,
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
