import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { api, errorText } from "./api";
import { ActionPanel } from "./Actions";
import { Avatar, Evidence } from "./components";
import { clearDraftKey, draftKey, useDraft } from "./drafts";
import { useGame } from "./state";
import type { Message, MessagePage } from "./types";

export function Chat({ onRole }: { onRole: (id: string) => void }) {
  const { state, session, messages, mergeMessages, connection, catalog } =
    useGame();
  const [messageScope, setMessageScope] = useState<
    "all" | "public" | "private" | "system" | "host"
  >("all");
  const [target, setTarget] = useState("public");
  const [sending, setSending] = useState(false);
  const [loading, setLoading] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [error, setError] = useState("");
  const [unread, setUnread] = useState(0);
  const scroller = useRef<HTMLDivElement>(null);
  const nearBottom = useRef(true);
  const previousLast = useRef(0);
  const restoreScroll = useRef<{ height: number; top: number } | null>(null);
  const channels = state?.channels ?? [
    {
      id: "public",
      label: "公共讨论",
      status: "active" as const,
      members: [],
      can_send: state?.can_chat ?? false,
      reason: state?.chat_reason,
    },
  ];
  const sendable = channels.filter((item) => item.can_send);
  const channel =
    channels.find((item) => item.id === target && item.can_send) ??
    sendable[0] ??
    channels[0];
  const activeId = channel?.id ?? "public";
  // 所选私密频道失效时静默回落会把私密草稿带进公屏：失效即清掉该频道草稿并提示。
  const invalidated = useRef<Set<string>>(new Set());
  useEffect(() => {
    for (const item of channels) {
      if (item.id === "public" || item.can_send || invalidated.current.has(item.id))
        continue;
      invalidated.current.add(item.id);
      clearDraftKey(
        draftKey(state?.id ?? null, session.actor?.id ?? null, "chat", item.id),
      );
      setError(`频道「${item.label}」已不可发言，其中的私密草稿已清除。`);
    }
  }, [channels, state?.id, session.actor?.id]);
  const feed = useRef<string | null>(null);
  feed.current = state?.id ?? null;
  const draftScope = draftKey(
    state?.id ?? null,
    session.actor?.id ?? null,
    "chat",
    activeId,
  );
  const [draft, setDraft, clearDraft, draftError] = useDraft(draftScope, "");
  const rows = messages.filter((message) => {
    if (messageScope === "all") return true;
    if (messageScope === "public")
      return message.kind === "chat" && message.channel_id === "public";
    if (messageScope === "private")
      return message.kind === "chat" && message.channel_id !== "public";
    if (messageScope === "host") return message.sender_id === "host";
    return ["notice", "presence", "information", "alert"].includes(
      message.kind,
    );
  });
  const channelActions = [
    ...(state?.actions.filter((action) => action.id.startsWith("channel.")) ?? []),
    ...channels.flatMap((item) => item.actions ?? []),
  ].filter(
    (action, index, all) =>
      all.findIndex(
        (item) =>
          item.id === action.id &&
          JSON.stringify(item.payload ?? {}) === JSON.stringify(action.payload ?? {}),
      ) === index,
  );
  const lastId = rows.at(-1)?.id ?? 0;
  const scrollBottom = () => {
    const node = scroller.current;
    if (node) node.scrollTop = node.scrollHeight;
    nearBottom.current = true;
    setUnread(0);
  };
  useEffect(() => {
    const observer = new ResizeObserver(() => {
      if (nearBottom.current) scrollBottom();
    });
    if (scroller.current) observer.observe(scroller.current);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (!state) return;
    const controller = new AbortController();
    setError("");
    setLoading(true);
    setHasMore(false);
    nearBottom.current = true;
    setUnread(0);
    previousLast.current = 0;
    api<MessagePage>(
      `/games/${state.id}/messages?scope=${messageScope}`,
      undefined,
      controller.signal,
    )
      .then((page) => {
        if (!controller.signal.aborted) {
          mergeMessages(page.messages);
          setHasMore(page.has_more);
        }
      })
      .catch((failure) => {
        if (!controller.signal.aborted) setError(errorText(failure));
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoading(false);
          requestAnimationFrame(scrollBottom);
        }
      });
    return () => controller.abort();
  }, [state?.id, messageScope, mergeMessages]);
  useLayoutEffect(() => {
    const node = scroller.current;
    if (!node) return;
    if (restoreScroll.current) {
      node.scrollTop =
        restoreScroll.current.top +
        node.scrollHeight -
        restoreScroll.current.height;
      restoreScroll.current = null;
    } else if (nearBottom.current) node.scrollTop = node.scrollHeight;
    else if (lastId > previousLast.current) {
      const count = rows.filter(
        (message) => message.id > previousLast.current,
      ).length;
      setUnread((previous) => previous + count);
    }
    previousLast.current = lastId;
  }, [lastId, rows.length, activeId]);
  const loadOlder = async () => {
    if (!state || loading || !rows.length) return;
    setLoading(true);
    setError("");
    try {
      const page = await api<MessagePage>(
        `/games/${state.id}/messages?before=${rows[0].id}&scope=${messageScope}`,
      );
      if (feed.current !== state.id) return;
      if (scroller.current)
        restoreScroll.current = {
          height: scroller.current.scrollHeight,
          top: scroller.current.scrollTop,
        };
      mergeMessages(page.messages);
      setHasMore(page.has_more);
    } catch (failure) {
      if (feed.current === state.id) setError(errorText(failure));
    } finally {
      if (feed.current === state.id) setLoading(false);
    }
  };
  const send = async (event: FormEvent) => {
    event.preventDefault();
    if (!state || sending || !draft.trim()) return;
    // 发送前按最新频道列表复核，绝不把私密内容发进已回落的公屏。
    const current = channels.find((item) => item.id === activeId);
    if (!current?.can_send) {
      setError(
        current?.reason ||
          state.chat_reason ||
          "所选频道当前不可发言；内容未发送，请重新选择频道。",
      );
      return;
    }
    if (!channel?.can_send) {
      setError(
        channel?.reason ||
          state.chat_reason ||
          "当前没有可以发言的频道；草稿已保留。",
      );
      return;
    }
    const recipient = activeId;
    const submitted = draft;
    setSending(true);
    setError("");
    try {
      const message = await api<Message>(`/games/${state.id}/messages`, {
        channel_id: recipient,
        text: submitted,
      });
      mergeMessages([message]);
      clearDraft();
      if (feed.current === state.id) {
        nearBottom.current = true;
        requestAnimationFrame(scrollBottom);
      }
    } catch (failure) {
      if (feed.current === state.id)
        setError(
          `${errorText(failure)} 草稿已保留；如响应丢失，请先检查记录是否已有此消息，再决定是否重发。`,
        );
    } finally {
      setSending(false);
    }
  };
  const ended = state?.status === "ended";
  return (
    <section className="chat-panel" aria-label="聊天记录与输入">
      <div className="chat-header">
        <div>
          <span className="eyebrow">公屏与私信独立查看 · 历史由服务器按权限筛选</span>
          <h2>{messageScope === "all" ? "全部消息" : "筛选消息"}</h2>
        </div>
        <div className="segmented" aria-label="消息筛选">
          {(
            ["all", "public", "private", "system", "host"] as const
          ).map((scope) => (
            <button
              type="button"
              key={scope}
              className={messageScope === scope ? "active" : ""}
              onClick={() => setMessageScope(scope)}
            >
              {{
                all: "全部",
                public: "公屏",
                private: "私信",
                system: "系统",
                host: "主持人",
              }[scope]}
            </button>
          ))}
        </div>
      </div>
      {channelActions.length > 0 && (
        <ActionPanel actions={channelActions} title="私信操作" />
      )}
      <div
        className="chat-scroll"
        ref={scroller}
        onPointerDown={() => {
          const active = document.activeElement;
          if (active instanceof HTMLTextAreaElement) active.blur();
        }}
        onScroll={() => {
          const node = scroller.current!;
          nearBottom.current =
            node.scrollHeight - node.scrollTop - node.clientHeight < 90;
          if (nearBottom.current) setUnread(0);
        }}
      >
        {hasMore && (
          <button
            className="load-older quiet"
            disabled={loading}
            onClick={() => void loadOlder()}
          >
            {loading ? "正在读取…" : "加载更早的消息"}
          </button>
        )}
        {!rows.length && (
          <div className="empty chat-empty">
            <span className="seal">言</span>
            <h3>{loading ? "正在读取对话" : "故事从第一句话开始"}</h3>
            <p>当前筛选范围内还没有消息。</p>
          </div>
        )}
        {rows.map((message) =>
          message.kind === "alert" ? (
            <p className="system-message alert" key={message.id}>
              <time dateTime={message.created_at}>
                {formatTime(message.created_at)}
              </time>
              <span>{message.text}</span>
            </p>
          ) : message.kind === "notice" || message.kind === "presence" ? (
            <p className={`system-message ${message.kind}`} key={message.id}>
              <time dateTime={message.created_at}>
                {formatTime(message.created_at)}
              </time>
              <span>{message.text}</span>
            </p>
          ) : (
            <article
              className={`message ${message.sender_id === session.actor?.id ? "mine" : ""} ${message.kind === "information" ? "information-message" : ""}`}
              key={message.id}
            >
              <Avatar
                name={message.sender_name}
                roleId={message.avatar_role_id}
                host={message.sender_id === "host"}
                onClick={
                  message.avatar_role_id && message.sender_id !== "host"
                    ? () => onRole(message.avatar_role_id!)
                    : undefined
                }
              />
              <div className="message-main">
                <div className="message-meta">
                  <strong>
                    {message.sender_name}
                    {message.avatar_role_id &&
                      message.sender_id !== "host" &&
                      `（${
                        catalog.roles.find(
                          (role) => role.id === message.avatar_role_id,
                        )?.name ?? message.avatar_role_id
                      }）`}
                  </strong>
                  {message.mimic_seat_id && (
                    <span className="tag gold">模仿 · 实为{message.mimic_seat_id}号</span>
                  )}
                  <time dateTime={message.created_at}>
                    {formatTime(message.created_at)}
                  </time>
                </div>
                <div className="bubble">
                  {message.channel_id !== "public" && (
                    <span className="message-type">
                      {message.kind === "information"
                        ? "系统信息"
                        : (channels.find(
                            (item) => item.id === message.channel_id,
                          )?.label ?? "私密频道")}
                    </span>
                  )}
                  <p>{message.text}</p>
                  {message.image_id && <Evidence id={message.image_id} />}
                </div>
              </div>
            </article>
          ),
        )}
      </div>
      {unread > 0 && (
        <button className="new-messages" onClick={scrollBottom}>
          {unread} 条新消息 · 回到最新 ↓
        </button>
      )}
      <form className="chat-compose" onSubmit={(event) => void send(event)}>
        <div className="compose-caption">
          <span className="send-target">
            发送至
            <select
              aria-label="选择发送频道"
              value={activeId}
              onChange={(event) => setTarget(event.target.value)}
            >
              {sendable.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.id === "public" ? "公共讨论" : item.label}
                </option>
              ))}
              {!sendable.length && <option value="public">暂无可用频道</option>}
            </select>
          </span>
          <span>{draft.length}/2000</span>
        </div>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {draftError && (
          <p className="warning" role="alert">
            {draftError}
          </p>
        )}
        <div className="compose-controls">
          <textarea
            aria-label="消息草稿"
            placeholder={
              ended
                ? "本局已结束，记录只读"
                : channel?.can_send
                  ? "说点什么…（草稿整局保留，换频道也不丢）"
                  : "当前不可发言，仍可先写草稿"
            }
            maxLength={2000}
            rows={2}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (
                event.key === "Enter" &&
                !event.shiftKey &&
                !event.nativeEvent.isComposing &&
                matchMedia("(pointer: fine)").matches
              ) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
          />
          <button
            className="primary"
            title={
              channel?.can_send
                ? "发送到所选频道"
                : channel?.reason || state?.chat_reason || "当前不能发言"
            }
            disabled={sending || !draft.trim() || !channel?.can_send || ended}
          >
            {sending ? "发送中…" : "发送"}
          </button>
        </div>
        <p className="hint">
          {ended
            ? "本局已结束，记录只读。"
            : !channel?.can_send
              ? channel?.reason ||
                state?.chat_reason ||
                "当前没有可以发言的频道；草稿会保留到本局结束。"
              : connection !== "online"
                ? "实时连接正在恢复；发送前请留意最新阶段。"
                : "文字可以复制、粘贴与转述；不提供来源引用认证。"}
        </p>
      </form>
    </section>
  );
}
/**
 * 服务端存的是 UTC 的 ISO-8601 串，界面统一换算成本机时区的精简时间：
 * 当天只显示时刻，跨天补日期，跨年补年份。无法解析时返回空串，
 * 绝不把原始时间串直接显示给用户。
 */
function formatTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (part: number) => String(part).padStart(2, "0");
  const time = `${pad(date.getHours())}:${pad(date.getMinutes())}`;
  const now = new Date();
  if (
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate()
  ) {
    return time;
  }
  const day = `${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
  return date.getFullYear() === now.getFullYear()
    ? `${day} ${time}`
    : `${date.getFullYear()}-${day} ${time}`;
}
