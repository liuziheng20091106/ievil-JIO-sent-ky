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
  const [channelId, setChannelId] = useState("public");
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
  const channel = channels.find((item) => item.id === channelId) ?? channels[0];
  const activeId = channel?.id ?? "public";
  const scope = draftKey(
    state?.id ?? null,
    session.actor?.id ?? null,
    "chat",
    activeId,
  );
  const [draft, setDraft, clearDraft, draftError] = useDraft(scope, "");
  const currentChannel = useRef(scope);
  currentChannel.current = scope;
  const rows = messages.filter((message) =>
    activeId === "system"
      ? message.channel_id === "information"
      : message.channel_id === activeId,
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
      `/games/${state.id}/messages?channel_id=${encodeURIComponent(activeId)}`,
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
  }, [state?.id, activeId, mergeMessages]);
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
        `/games/${state.id}/messages?channel_id=${encodeURIComponent(activeId)}&before=${rows[0].id}`,
      );
      if (currentChannel.current !== scope) return;
      if (scroller.current)
        restoreScroll.current = {
          height: scroller.current.scrollHeight,
          top: scroller.current.scrollTop,
        };
      mergeMessages(page.messages);
      setHasMore(page.has_more);
    } catch (failure) {
      if (currentChannel.current === scope) setError(errorText(failure));
    } finally {
      if (currentChannel.current === scope) setLoading(false);
    }
  };
  const send = async (event: FormEvent) => {
    event.preventDefault();
    if (
      !state ||
      sending ||
      !draft.trim() ||
      !channel?.can_send ||
      state.status === "ended"
    )
      return;
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
      if (scope === currentChannel.current) {
        nearBottom.current = true;
        requestAnimationFrame(scrollBottom);
      }
    } catch (failure) {
      if (scope === currentChannel.current)
        setError(
          `${errorText(failure)} 草稿已保留；如响应丢失，请先检查记录是否已有此消息，再决定是否重发。`,
        );
    } finally {
      setSending(false);
    }
  };
  const systemChannel = activeId === "system";
  const privateChannel = activeId !== "public" && !systemChannel;
  return (
    <section className="chat-panel" aria-label="聊天记录与输入">
      <div className={`chat-header ${privateChannel ? "private-channel" : ""}`}>
        <div>
          <span className="eyebrow">
            {systemChannel
              ? "发给你的通知与裁定 · 只读"
              : privateChannel
                ? "仅授权成员可见 · 私密频道"
                : "全体成员可见 · 公开频道"}
          </span>
          <h2>{channel?.label ?? "公共讨论"}</h2>
        </div>
        <label className="channel-picker">
          <span className="sr-only">切换聊天频道</span>
          <select
            value={activeId}
            onChange={(event) => setChannelId(event.target.value)}
          >
            {channels.map((item) => (
              <option key={item.id} value={item.id}>
                {item.id === "public"
                  ? "公开"
                  : item.id === "system"
                    ? "系统"
                    : "私密"}{" "}
                · {item.label}
              </option>
            ))}
          </select>
        </label>
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
              {systemChannel
                ? "这里集中显示发给你一个人的通知、裁定与私密信息；其他玩家看不到。"
                : privateChannel
                  ? "这个频道的内容仅发送给获准成员。主持人可查看所有频道。"
                  : "只使用公开身份发言。你的另一张牌，仍属于你自己的秘密。"}
            </p>
          </div>
        )}
        {rows.map((message) =>
          message.kind === "notice" || message.kind === "presence" ? (
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
                  {message.kind === "information" && (
                    <span className="message-type">信息</span>
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
          <span>
            {systemChannel
              ? "系统信息只读，不能在此发言"
              : privateChannel
                ? `私密发送至：${channel?.label}`
                : "发送至：公共讨论"}
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
            aria-label={`发消息到${channel?.label}`}
            placeholder={
              channel?.can_send && state?.status !== "ended"
                ? "说点什么…"
                : "当前不可发言"
            }
            maxLength={2000}
            rows={2}
            value={draft}
            disabled={!channel?.can_send || state?.status === "ended"}
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
            disabled={
              sending ||
              !draft.trim() ||
              !channel?.can_send ||
              state?.status === "ended"
            }
          >
            {sending ? "发送中…" : "发送"}
          </button>
        </div>
        <p className="hint">
          {state?.status === "ended"
            ? "本局已结束，记录只读。"
            : !channel?.can_send
              ? channel?.reason ||
                state?.chat_reason ||
                "当前频道不允许发言，请等待主持人安排。"
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
