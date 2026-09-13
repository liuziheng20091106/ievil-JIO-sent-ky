import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { api, errorText } from "./api";
import { Avatar, Evidence } from "./components";
import { draftKey, useDraft } from "./drafts";
import { useGame } from "./state";
import type { Message, MessagePage } from "./types";

export function Chat({ onRole }: { onRole: (id: string) => void }) {
  const { state, session, messages, mergeMessages, connection, catalog } =
    useGame();
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
      can_send: state?.can_chat ?? false,
      reason: state?.chat_reason,
    },
  ];
  const sendable = channels.filter((item) => item.can_send);
  const channel = sendable.find((item) => item.id === target) ?? sendable[0];
  const activeId = channel?.id ?? "public";
  const feed = useRef<string | null>(null);
  feed.current = state?.id ?? null;
  const scope = draftKey(
    state?.id ?? null,
    session.actor?.id ?? null,
    "chat",
    activeId,
  );
  const [draft, setDraft, clearDraft, draftError] = useDraft(scope, "");
  const rows = messages;
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
      `/games/${state.id}/messages`,
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
  }, [state?.id, mergeMessages]);
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
        `/games/${state.id}/messages?before=${rows[0].id}`,
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
          <span className="eyebrow">公开与私密已合并 · 只显示你有权看到的</span>
          <h2>全部消息</h2>
        </div>
      </div>
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
            <p>
              这里按时间顺序合并显示你有权看到的全部消息：公开讨论、私聊，以及只发给你的系统裁定与私密信息。
            </p>
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
            aria-label={`草稿：发送至${channel?.label ?? "公共讨论"}`}
            placeholder={
              ended
                ? "本局已结束，记录只读"
                : channel?.can_send
                  ? "说点什么…（草稿按频道分别保存）"
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
                "当前没有可以发言的频道；草稿会按频道保留。"
              : connection !== "online"
                ? "实时连接正在恢复；发送前请留意最新阶段。"
                : "文字可以复制、粘贴与转述；不提供来源引用认证。"}
        </p>
      </form>
    </section>
  );
}
function formatTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}
