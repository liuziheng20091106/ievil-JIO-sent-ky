import { useEffect, useRef, useState, type FormEvent } from "react";
import { ActionPanel, type PanelRequest } from "./Actions";
import { api, errorText } from "./api";
import { Chat } from "./Chat";
import {
  Avatar,
  Evidence,
  labelFor,
  Modal,
  RecordView,
  RoleCard,
} from "./components";
import { draftKey, useDraft } from "./drafts";
import { useGame } from "./state";
import type {
  GameView,
  HostTask,
  Lobby,
  LoginChallenge,
  Message,
  Seat,
  SeatView,
  Session,
  UIAction,
} from "./types";

type Tab = "chat" | "table" | "cards" | "actions" | "manage";
export function App() {
  const { session, state, catalog, loading, error, setError, refresh, logout } =
    useGame();
  const [roleId, setRoleId] = useState<string | null>(null);
  const [rules, setRules] = useState(false);
  const [newGame, setNewGame] = useState(false);
  const [logoutBusy, setLogoutBusy] = useState(false);
  useEffect(() => {
    const viewport = window.visualViewport;
    const resize = () =>
      document.documentElement.style.setProperty(
        "--app-height",
        `${viewport?.height ?? window.innerHeight}px`,
      );
    // iOS pans the visual viewport up to reveal the caret; pin the layout back.
    const pinTop = () => {
      if (viewport && viewport.offsetTop > 0) window.scrollTo(0, 0);
    };
    resize();
    viewport?.addEventListener("resize", resize);
    viewport?.addEventListener("scroll", pinTop);
    window.addEventListener("resize", resize);
    return () => {
      viewport?.removeEventListener("resize", resize);
      viewport?.removeEventListener("scroll", pinTop);
      window.removeEventListener("resize", resize);
    };
  }, []);
  const role = catalog.roles.find((item) => item.id === roleId);
  const exit = async () => {
    setLogoutBusy(true);
    try {
      await logout();
      setNewGame(false);
    } catch (failure) {
      setError(errorText(failure));
    } finally {
      setLogoutBusy(false);
    }
  };
  return (
    <>
      {loading ? (
        <main className="loading-screen">
          <span className="seal">七</span>
          <h1>正在翻开魔典</h1>
          <p>连接本局，恢复你的席位与记录…</p>
        </main>
      ) : (
        <>
          <header className="app-header">
            <a
              className="brand"
              href="/"
              onClick={(event) => {
                event.preventDefault();
                if (!state) void refresh();
              }}
              aria-label="魔法裁判七双首页"
            >
              <span className="brand-mark">七</span>
              <span>
                <strong>魔法裁判</strong>
                <small>七双 · SEVEN / DOUBLE</small>
              </span>
            </a>
            <div className="header-actions">
              <button className="quiet" onClick={() => setRules(true)}>
                角色图鉴
              </button>
              {session.actor && (
                <>
                  <span className="identity-label">
                    {session.actor.kind === "host"
                      ? "主持人 · 月代雪"
                      : session.actor.kind === "account"
                        ? `QQ · ${session.actor.name}`
                        : session.actor.kind === "spectator"
                          ? `观战 · ${session.actor.name}`
                          : `${session.actor.seat_id}号 · ${session.actor.name}`}
                  </span>
                  <button
                    className="quiet"
                    disabled={logoutBusy}
                    onClick={() => void exit()}
                  >
                    {logoutBusy ? "退出中…" : "退出"}
                  </button>
                </>
              )}
            </div>
          </header>
          {error && (
            <div className="global-error" role="alert">
              <span>{error}</span>
              <button className="quiet" onClick={() => void refresh()}>
                重新连接
              </button>
              <button
                className="quiet"
                aria-label="关闭错误提示"
                onClick={() => setError("")}
              >
                ×
              </button>
            </div>
          )}
          {!session.actor ? (
            <Entry />
          ) : session.actor.kind === "host" && (!state || newGame) ? (
            <CreateGame
              onCreated={() => setNewGame(false)}
              onCancel={state ? () => setNewGame(false) : undefined}
            />
          ) : session.actor.kind === "account" && !state ? (
            <LobbyEntry />
          ) : state ? (
            <Room onRole={setRoleId} onNewGame={() => setNewGame(true)} />
          ) : (
            <main className="loading-screen">
              <h1>暂时无法读取本局</h1>
              <p>你的身份已登录。请重新连接以获取获准查看的状态。</p>
              <button className="primary" onClick={() => void refresh()}>
                重新获取状态
              </button>
            </main>
          )}
        </>
      )}
      {rules && (
        <Modal title="十四角色 · 魔法图鉴" onClose={() => setRules(false)} wide>
          <p className="hint">
            角色说明由本局服务器提供。查看公开角色图鉴并不代表知道他人的真实角色。
          </p>
          <div className="catalog-grid">
            {catalog.roles.map((item) => (
              <button
                className="catalog-tile"
                key={item.id}
                onClick={() => {
                  setRules(false);
                  setRoleId(item.id);
                }}
              >
                {item.avatar ? (
                  <img
                    src={item.avatar}
                    alt={`${item.name}立绘`}
                    loading="lazy"
                  />
                ) : (
                  <span className="honoka-art">穗</span>
                )}
                <strong>{item.name}</strong>
              </button>
            ))}
          </div>
          {!catalog.roles.length && <p>角色目录尚未加载，请重新连接。</p>}
        </Modal>
      )}
      {role && (
        <Modal title={role.name} onClose={() => setRoleId(null)}>
          <div className="role-detail">
            {role.avatar ? (
              <img src={role.avatar} alt={`${role.name}完整立绘`} />
            ) : (
              <span className="honoka-art">穗</span>
            )}
            <div>
              <span className="eyebrow">普通状态</span>
              <p>{role.normal}</p>
              <span className="eyebrow witch-text">魔女化</span>
              <p>{role.witch}</p>
            </div>
          </div>
        </Modal>
      )}
    </>
  );
}

function Entry() {
  const { authenticate, refresh } = useGame();
  const [mode, setMode] = useState<"qq" | "host">("qq");
  const [challenge, setChallenge] = useState<LoginChallenge | null>(null);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!challenge || challenge.status !== "pending") return;
    let active = true;
    let timer: NodeJS.Timeout | undefined;
    const poll = async () => {
      try {
        const next = await api<LoginChallenge>(
          `/auth/challenges/${encodeURIComponent(challenge.id)}`,
        );
        if (!active) return;
        setChallenge(next);
        if (next.status === "completed") await refresh();
        else timer = setTimeout(() => void poll(), 1500);
      } catch (failure) {
        if (active) setError(errorText(failure));
      }
    };
    timer = setTimeout(() => void poll(), 800);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [challenge?.id, challenge?.status, refresh]);

  const startQQ = async () => {
    setBusy(true);
    setError("");
    try {
      setChallenge(await api<LoginChallenge>("/auth/challenges", {}));
    } catch (failure) {
      setError(errorText(failure));
    } finally {
      setBusy(false);
    }
  };

  const submitHost = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await authenticate("/host/login", { password });
      setPassword("");
    } catch (failure) {
      setError(errorText(failure));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="entry-layout">
      <section className="entry-story">
        <p className="eyebrow">一场关于信任、记忆与另一重身份的审判</p>
        <h1>
          每个人，
          <br />
          都有<span>另一面。</span>
        </h1>
        <p className="story-copy">
          七位玩家，十四张角色牌。
          <br />
          在白昼留下证词，在夜里藏好秘密。
          <br />
          下一页魔典，将写下谁的名字？
        </p>
        <div className="story-facts">
          <div>
            <strong>07</strong>
            <span>玩家席位</span>
          </div>
          <div>
            <strong>14</strong>
            <span>双重角色</span>
          </div>
          <div>
            <strong>01</strong>
            <span>共同的故事</span>
          </div>
        </div>
        <div className="hero-art" aria-hidden="true">
          <img src="/assets/characters/月代雪.png" alt="" />
          <span>月代雪 / 主持人</span>
        </div>
        <p className="entry-footnote">文字讨论 · 私密行动 · 主持人裁决</p>
      </section>
      <section className="entry-form panel">
        <span className="eyebrow">欢迎来到魔法裁判</span>
        <h2>{mode === "qq" ? "登录后主动加入或观战。" : "今晚，由你翻开魔典。"}</h2>
        <div className="segmented" aria-label="选择登录方式">
          <button
            className={mode === "qq" ? "active" : ""}
            onClick={() => {
              setMode("qq");
              setError("");
            }}
          >
            QQ 登录
          </button>
          <button
            className={mode === "host" ? "active" : ""}
            onClick={() => {
              setMode("host");
              setError("");
            }}
          >
            主持人登录
          </button>
        </div>
        {mode === "qq" ? (
          <div className="entry-login-flow">
            <p className="hint">
              生成验证码后，在指定 QQ 群发送完整文字。群内昵称和头像将作为本局公开身份。
            </p>
            {challenge?.status === "pending" && challenge.code && (
              <div className="invite-code" role="status">
                <span className="eyebrow">请在 QQ 群发送</span>
                <input
                  readOnly
                  value={`活动登录 ${challenge.code}`}
                  onFocus={(event) => event.currentTarget.select()}
                />
                <small>
                  验证码有效至
                  {new Date(challenge.expires_at).toLocaleTimeString("zh-CN")}
                </small>
              </div>
            )}
            <button
              type="button"
              className="primary full-width"
              disabled={busy}
              onClick={() => void startQQ()}
            >
              {busy
                ? "正在生成…"
                : challenge
                  ? "重新生成验证码"
                  : "生成 QQ 登录码"}
            </button>
          </div>
        ) : (
          <form onSubmit={(event) => void submitHost(event)}>
            <label className="field">
              <span>主持人密码</span>
              <input
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="输入主持人密码"
              />
            </label>
            <p className="hint">
              主持人可以查看本局全部角色与私密信息。请勿向玩家共享你的会话。
            </p>
            <button className="primary full-width" disabled={busy}>
              {busy ? "正在进入…" : "进入主持人工作台 →"}
            </button>
          </form>
        )}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <div className="entry-note">
          <span>持久登录</span>
          <p>验证成功后按 QQ 账号恢复参与身份；刷新、换设备或重连不会重新分席。</p>
        </div>
      </section>
    </main>
  );
}

function LobbyEntry() {
  const { refresh } = useGame();
  const [lobby, setLobby] = useState<Lobby | null>(null);
  const [busy, setBusy] = useState<"player" | "spectator" | "">("");
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    api<Lobby>("/lobby", undefined, controller.signal)
      .then(setLobby)
      .catch((failure) => {
        if (!controller.signal.aborted) setError(errorText(failure));
      });
    return () => controller.abort();
  }, []);

  const participate = async (kind: "player" | "spectator") => {
    if (!lobby?.game) return;
    setBusy(kind);
    setError("");
    try {
      await api<Session>(`/games/${lobby.game.id}/participations`, { kind });
      await refresh();
    } catch (failure) {
      setError(errorText(failure));
    } finally {
      setBusy("");
    }
  };

  return (
    <main className="loading-screen lobby-entry">
      <span className="seal">候</span>
      <h1>{lobby?.game ? "本局已开放" : "等待主持人开放对局"}</h1>
      {lobby?.game ? (
        <>
          <p>
            当前还有 {lobby.game.player_seats_available} 个玩家席位。选择后立即生效，无需主持人审核。
          </p>
          <div className="button-row">
            <button
              className="primary"
              disabled={busy !== "" || !lobby.game.can_join_player}
              onClick={() => void participate("player")}
            >
              {busy === "player" ? "加入中…" : "加入对局"}
            </button>
            <button
              className="secondary"
              disabled={busy !== "" || !lobby.game.can_join_spectator}
              onClick={() => void participate("spectator")}
            >
              {busy === "spectator" ? "进入中…" : "选择观战"}
            </button>
          </div>
        </>
      ) : (
        <p>你已登录。主持人宣布对局可用后，可直接选择加入或观战。</p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <button className="quiet" onClick={() => location.reload()}>
        刷新大厅
      </button>
    </main>
  );
}

function CreateGame({
  onCreated,
  onCancel,
}: {
  onCreated: () => void;
  onCancel?: () => void;
}) {
  const { catalog, create, session, setError: setGlobalError } = useGame();
  const [selected, setSelected, clearDraft, draftError] = useDraft<string[]>(
    draftKey(session.game_id, session.actor?.id ?? null, "create"),
    catalog.default_codex,
  );
  const [confirmed, setConfirmed] = useState(false);
  const [review, setReview] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      await create(selected);
      try {
        clearDraft();
      } catch (failure) {
        setGlobalError(errorText(failure));
      }
      onCreated();
    } catch (failure) {
      setError(errorText(failure));
    } finally {
      setBusy(false);
    }
  };
  return (
    <main className="create-page">
      <div className="page-intro">
        <span className="eyebrow">主持人 · 建立新对局</span>
        <h1>确认魔典，再让命运发牌。</h1>
        <p>
          选择本局的11名魔典角色并随机排列。创建后先邀请七位玩家入席，全员首次准备后才随机分配双牌。
        </p>
      </div>
      <section className="panel codex-picker">
        <div className="section-heading">
          <h2>魔典角色</h2>
          <span className={selected.length === 11 ? "tag gold" : "tag"}>
            {selected.length} / 11
          </span>
        </div>
        <div className="codex-grid">
          {catalog.roles.map((role) => (
            <label
              key={role.id}
              className={`codex-option ${selected.includes(role.id) ? "selected" : ""}`}
            >
              <input
                type="checkbox"
                checked={selected.includes(role.id)}
                disabled={!selected.includes(role.id) && selected.length >= 11}
                onChange={(event) => {
                  setSelected((previous) =>
                    event.target.checked
                      ? [...previous, role.id]
                      : previous.filter((id) => id !== role.id),
                  );
                  setConfirmed(false);
                }}
              />
              {role.avatar ? (
                <img src={role.avatar} alt={`${role.name}角色立绘`} />
              ) : (
                <span className="honoka-art">穗</span>
              )}
              <strong>{role.name}</strong>
            </label>
          ))}
        </div>
        <label className="check-row confirm-codex">
          <input
            type="checkbox"
            checked={confirmed}
            disabled={selected.length !== 11}
            onChange={(event) => setConfirmed(event.target.checked)}
          />
          <span>
            我已确认这11名角色为本局魔典名单，实际转化顺序由系统随机生成。
          </span>
        </label>
        {draftError && (
          <p className="error" role="alert">
            {draftError}
          </p>
        )}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <div className="form-footer">
          {onCancel && (
            <button className="quiet" onClick={onCancel}>
              返回本局
            </button>
          )}
          <button
            className="primary"
            disabled={selected.length !== 11 || !confirmed || busy}
            onClick={() => setReview(true)}
          >
            确认名单，建立候场
          </button>
        </div>
      </section>
      {review && (
        <Modal
          title="确认建立新对局"
          onClose={() => {
            if (!busy) setReview(false);
          }}
        >
          <p>本局魔典名单：</p>
          <div className="tags">
            {selected.map((id) => (
              <span className="tag gold" key={id}>
                {catalog.roles.find((role) => role.id === id)?.name}
              </span>
            ))}
          </div>
          <p>
            将随机生成魔典顺序并建立七个空席。创建后由主持人点击“开放加入”，已登录账号即可主动选择玩家或观战。
          </p>
          <p className="hint">
            建立新对局会清空上一局的参与身份、进度、聊天与证物，但不会删除 QQ 账号或登录令牌。
          </p>
          <button
            className="primary full-width"
            disabled={busy}
            onClick={() => void submit()}
          >
            {busy ? "正在创建…" : "确认创建候场"}
          </button>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
        </Modal>
      )}
    </main>
  );
}

const phaseHints: Record<string, string> = {
  lobby: "主持人开放加入后，登录玩家主动入席并点「准备」；七人全部准备后系统自动发牌。",
  ordering: "私下选定上层牌后再次「准备」；七人齐全由主持人开局。",
  witch:
    "系统检测本日魔女化并私下通知被选中的人；无人需要操作，稍候自动进入夜晚。",
  night:
    "有夜间技能的席位私下选目标并「确认已选行动」；没有技能的席位已自动放弃。",
  night_coco: "魔女可可在参考已确认的夜间行动后最后提交；其他席位等待。",
  night_review: "主持人审阅预结算、处理待裁定事项，然后公布夜间结果。",
  night_results: "主持人公布死亡与证物；本夜出局者可在此阶段提交遗留证物。",
  speech:
    "按发言顺序依次出声；轮到你时说完点「结束本次发言」交给下一位。未轮到的席位可以「提前发言」（写下内容立即公开）或「本轮不发言（跳过我的顺序）」。",
  discussion: "自由讨论；主持人认为讨论充分后推进到热气球。",
  balloon: "热气球参与者私下提交「制作」或「破坏」；其他人等待。",
  nomination:
    "各自提名一个席位或「放弃本次提名」，可提前提交；进入本阶段时先前提名自动确认。",
  voting: "对当前候选投同意／不同意／弃票；提名过该候选的人已自动投同意。",
  execution: "被处决席位确认临刑行动（奈乃香可临刑开枪）；其他席位等待。",
  dusk: "主持人确认胜负与结算效果，然后进入下一夜。",
};

function Room({
  onRole,
  onNewGame,
}: {
  onRole: (id: string) => void;
  onNewGame: () => void;
}) {
  const { state, session, connection, busy, messages } = useGame();
  const [tab, setTab] = useState<Tab>("chat");
  const [center, setCenter] = useState<"chat" | "table">("chat");
  const [side, setSide] = useState<"cards" | "actions">("actions");
  const [management, setManagement] = useState(false);
  const [request, setRequest] = useState<PanelRequest | null>(null);
  const actionFormOpen = useRef(false);
  const [inspecting, setInspecting] = useState<string | null>(null);
  const [flash, setFlash] = useState("");
  const [alerts, setAlerts] = useState<Message[]>([]);
  const seenMessage = useRef<number | null>(null);
  useEffect(() => {
    if (!messages.length) return;
    const latest = messages[messages.length - 1].id;
    const previous = seenMessage.current;
    seenMessage.current = latest;
    if (previous === null) return; // 首次载入只记录游标，不跳转也不弹窗
    const fresh = messages.filter(
      (item) =>
        item.id > previous &&
        item.kind !== "presence" &&
        item.sender_id !== session.actor?.id,
    );
    if (!fresh.length) return;
    if (!actionFormOpen.current) {
      // 手机上正在填行动窗口时不打断，聊天内容照常进记录与悬浮提醒
      setCenter("chat");
      setTab("chat");
    }
    const mustNotice = fresh.filter(
      (item) => item.kind === "information" || item.kind === "alert",
    );
    if (mustNotice.length)
      setAlerts((previousAlerts) =>
        [...previousAlerts, ...mustNotice].slice(-3),
      );
  }, [messages, session.actor?.id]);
  const phaseKey = state ? `${state.day}:${state.half}:${state.phase}` : "";
  const flashText = state ? `第 ${state.day} 日 · ${state.phase_label}` : "";
  const lastPhase = useRef("");
  const phaseTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (!phaseKey || lastPhase.current === phaseKey) return;
    if (!lastPhase.current) {
      lastPhase.current = phaseKey;
      return;
    }
    lastPhase.current = phaseKey;
    setFlash(flashText);
    if (phaseTimer.current) clearTimeout(phaseTimer.current);
    phaseTimer.current = setTimeout(() => setFlash(""), 5000);
  }, [phaseKey, flashText]);
  useEffect(() => {
    if (state?.status === "ended") {
      setTab("table");
      setCenter("table");
    } else if (state?.status === "lobby") {
      setTab(
        session.actor?.kind === "host"
          ? "manage"
          : session.actor?.kind === "player"
            ? "cards"
            : "table",
      );
      setCenter("table");
      setSide(session.actor?.kind === "player" ? "cards" : "actions");
    }
  }, [state?.id, state?.status, session.actor?.kind]);
  if (!state) return null;
  const isHost = session.actor?.kind === "host";
  const isObserver = session.actor?.kind === "spectator";
  const urgent = state.actions.filter((item) => item.blocking);
  const hostTasks = state.host?.tasks ?? [];
  const blockingTasks = hostTasks.filter(
    (item) => item.blocking && item.action !== "host.advance",
  );
  const actor = state.public.current_actor;
  const hint =
    state.status === "playing" || state.status === "lobby"
      ? phaseHints[state.phase]
      : undefined;
  const revealActions = () => {
    setTab("actions");
    setSide("actions");
  };
  const pick = (
    id: string,
    payload?: Record<string, unknown>,
    values?: Record<string, unknown>,
  ) => setRequest({ id, payload, values, token: Date.now() });
  const advanceAction = state.actions.find((item) => item.id === "host.advance");
  const autoToggle = state.actions.find((item) => item.id === "host.auto");
  const autoPaused = state.public.auto_advance_off === true;
  const tabs: { id: Tab; label: string; count?: number; urgent?: boolean }[] = [
    { id: "chat", label: "聊天" },
    { id: "table", label: "桌面" },
    isHost
      ? { id: "actions", label: "裁决", count: blockingTasks.length }
      : { id: "cards", label: isObserver ? "信息" : "我的牌" },
    isHost
      ? {
          id: "manage",
          label: "管理",
          count: hostTasks.length,
          urgent: blockingTasks.length > 0,
        }
      : {
          id: "actions",
          label: "行动",
          count: urgent.length,
          urgent: urgent.length > 0,
        },
  ];
  return (
    <main
      className={`room ${isHost ? "host-room" : ""}`}
      data-mobile-tab={tab}
      data-center-tab={center}
      data-side-tab={side}
    >
      <div className={`phase-bar ${state.half === "night" ? "night" : "day"}`}>
        <div className="phase-title">
          <span className="phase-symbol" aria-hidden="true">
            {state.half === "night" ? "☾" : "◉"}
          </span>
          <div>
            <span className="eyebrow">
              {state.status === "lobby"
                ? "等待故事开始"
                : state.status === "ended"
                  ? "本局已落幕"
                  : `第 ${state.day} 日 · ${state.half === "night" ? "夜晚" : "白天"}`}
            </span>
            <h1>{state.phase_label}</h1>
          </div>
          {hint && (
            <p className="phase-hint">
              <span className="eyebrow">现在做什么</span>
              {hint}
            </p>
          )}
        </div>
        <div className="phase-meta">
          {actor && (
            <span
              className={`phase-actor ${
                actor.seat_id && actor.seat_id === state.self.seat_id
                  ? "own-turn"
                  : ""
              }`}
            >
              {actor.seat_id ? `${seatLabel(state, actor.seat_id)} · ` : ""}
              {actor.label}
            </span>
          )}
          <span className={`connection ${connection}`}>
            <i />
            {connection === "online"
              ? "实时已连接"
              : connection === "connecting"
                ? "正在连接…"
                : connection === "unauthorized"
                  ? "会话已失效"
                  : "离线 · 正在恢复"}
          </span>
          <Countdown deadline={state.deadline} label="阶段计时" />
          <Countdown
            deadline={state.public.auto_advance_at ?? null}
            label="自动推进"
          />
          {isHost && advanceAction && (
            <button
              className="primary advance-button"
              disabled={busy || blockingTasks.length > 0}
              title={
                blockingTasks.length
                  ? `还有 ${blockingTasks.length} 项待处理，见「裁决」列表`
                  : advanceAction.description || advanceAction.label
              }
              onClick={() => pick("host.advance")}
            >
              {blockingTasks.length
                ? `${blockingTasks.length}项待办`
                : advanceAction.short_label}
            </button>
          )}
          {isHost && autoToggle && (
            <button
              className="quiet auto-toggle"
              disabled={busy}
              title={
                autoPaused
                  ? "恢复后：无人待办时 5 秒自动进入下一阶段"
                  : "暂停后本阶段只由主持人手动推进"
              }
              onClick={() => pick("host.auto")}
            >
              {autoToggle.short_label}
            </button>
          )}
          {isHost && (
            <button
              className="quiet desktop-only"
              onClick={() => setManagement(true)}
            >
              房间管理
            </button>
          )}
        </div>
      </div>
      {!isHost && (urgent.length > 0 || state.self.warning_deadline) && (
        <button
          className={`urgent-banner ${
            state.self.warning_deadline ? "warned" : ""
          }`}
          onClick={revealActions}
        >
          <strong>
            {urgent.length
              ? `轮到你行动：${urgent.map((item) => item.label).join("、")}`
              : "主持人正在等待你的操作"}
          </strong>
          <Countdown
            deadline={state.self.warning_deadline ?? null}
            label="主持人警告"
          />
          <span className="urgent-hint">点击前往「行动」</span>
        </button>
      )}
      {flash && (
        <div className="phase-flash" role="status">
          <span className="eyebrow">阶段已推进</span>
          <strong>{flash}</strong>
        </div>
      )}
      {alerts.length > 0 && (
        <div className="alert-stack" role="status" aria-live="polite">
          {alerts.map((item) => (
            <article
              className={`alert-card ${item.kind === "alert" ? "public-alert" : ""}`}
              key={item.id}
            >
              <div className="alert-head">
                <span className="eyebrow">
                  {item.kind === "alert" ? "全场公告" : "系统与私密信息"}
                </span>
                <button
                  className="quiet"
                  aria-label="关闭这条提醒"
                  onClick={() =>
                    setAlerts((previous) =>
                      previous.filter((alert) => alert.id !== item.id),
                    )
                  }
                >
                  ✕
                </button>
              </div>
              <p>{item.text}</p>
              {item.image_id && <Evidence id={item.image_id} />}
              <button
                className="quiet"
                onClick={() => {
                  setCenter("chat");
                  setTab("chat");
                  setAlerts((previous) =>
                    previous.filter((alert) => alert.id !== item.id),
                  );
                }}
              >
                前往对话记录
              </button>
            </article>
          ))}
        </div>
      )}
      <aside className="seat-column panel">
        <div className="section-heading">
          <h2>七席</h2>
          <span className="count">
            {state.seats.filter((seat) => seat.occupied).length}/7
          </span>
        </div>
        <p className="hint">
          {isHost ? "公开身份 · 私密牌面见管理" : "这里只展示公开身份"}
        </p>
        <SeatList
          seats={state.seats}
          onRole={onRole}
          onInspect={isHost ? setInspecting : undefined}
        />
        <div className="host-signature">
          <Avatar name="主持人" host />
          <div>
            <strong>月代雪</strong>
            <small>本局主持人</small>
          </div>
        </div>
      </aside>
      <section className="center-column">
        <div className="desktop-tabs">
          <button
            className={center === "chat" ? "active" : ""}
            onClick={() => setCenter("chat")}
          >
            对话记录
          </button>
          <button
            className={center === "table" ? "active" : ""}
            onClick={() => setCenter("table")}
          >
            公共桌面{state.status === "ended" ? " · 结局" : ""}
          </button>
        </div>
        <div className="chat-surface">
          <Chat onRole={onRole} />
        </div>
        <div className="table-surface panel scroll-panel">
          <PublicTable
            onRole={onRole}
            onNewGame={onNewGame}
            onInspect={isHost ? setInspecting : undefined}
          />
        </div>
      </section>
      <aside className="side-column panel">
        <div className="desktop-tabs">
          <button
            className={side === "actions" ? "active" : ""}
            onClick={() => setSide("actions")}
          >
            {isHost ? "裁决与行动" : "当前行动"}
            <span className="count">{state.actions.length}</span>
          </button>
          <button
            className={side === "cards" ? "active" : ""}
            onClick={() => setSide("cards")}
          >
            {isHost ? "全局信息" : isObserver ? "可见信息" : "我的双牌"}
          </button>
        </div>
        <div className="side-scroll">
          <div className="actions-surface">
            {isHost && state.host && (
              <HostTasks
                onPick={pick}
                onWarn={(seatId) =>
                  pick("host.warn", undefined, { seat_id: seatId })
                }
              />
            )}
            {isHost && (
              <NightLedger
                onWarn={(seatId) =>
                  pick("host.warn", undefined, { seat_id: seatId })
                }
              />
            )}
            <ActionPanel
              actions={state.actions}
              title={isHost ? "主持人操作" : "本阶段行动"}
              request={request}
              onRequestHandled={() => setRequest(null)}
              onOpenChange={(open) => {
                actionFormOpen.current = open;
              }}
            />
          </div>
          <div className="cards-surface">
            <PrivatePanel onRole={onRole} />
          </div>
        </div>
      </aside>
      <section className="mobile-management panel scroll-panel">
        <HostManagement onRole={onRole} onInspect={setInspecting} />
        <details className="record-section">
          <summary>全局私密信息、夜间意图与时间快照</summary>
          <PrivatePanel onRole={onRole} />
        </details>
      </section>
      <nav className="bottom-nav" aria-label="游戏导航">
        {tabs.map((item) => (
          <button
            key={item.id}
            className={`${tab === item.id ? "active" : ""} ${
              item.urgent ? "urgent" : ""
            }`}
            aria-current={tab === item.id ? "page" : undefined}
            onClick={() => setTab(item.id)}
          >
            <span>{item.label}</span>
            {Boolean(item.count) && (
              <small className={item.urgent ? "urgent" : ""}>
                {item.count}
              </small>
            )}
          </button>
        ))}
      </nav>
      {management && (
        <Modal
          title="主持人 · 房间管理"
          onClose={() => setManagement(false)}
          wide
        >
          <HostManagement onRole={onRole} onInspect={setInspecting} />
        </Modal>
      )}
      {isHost && inspecting && (
        <Modal
          title={`席位视角 · ${inspecting}号`}
          onClose={() => setInspecting(null)}
          wide
        >
          <SeatInspector seatId={inspecting} />
        </Modal>
      )}
    </main>
  );
}

function Countdown({
  deadline,
  label = "已警告",
}: {
  deadline: number | null;
  label?: string;
}) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!deadline) return;
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [deadline]);
  if (!deadline) return null;
  const seconds = Math.max(0, Math.ceil((deadline * 1000 - now) / 1000));
  return (
    <span className="countdown" role="timer">
      {seconds > 0
        ? `${label} · 剩余 ${seconds} 秒`
        : `${label} · 计时结束，等待服务器结算`}
    </span>
  );
}

function seatLabel(state: GameView, id: string) {
  const seat = state.seats.find((item) => item.id === id);
  return `${id}号${seat?.name ? ` ${seat.name}` : ""}`;
}

function currentRoleId(state: GameView, id: string) {
  const seat = state.seats.find((item) => item.id === id);
  const card = seat?.cards?.find((item) => item.alive) ?? seat?.cards?.[0];
  return card?.role_id ?? "";
}

function SeatList({
  seats,
  onRole,
  onInspect,
}: {
  seats: Seat[];
  onRole: (id: string) => void;
  onInspect?: (id: string) => void;
}) {
  const { state, catalog } = useGame();
  const roleName = (id: string | null | undefined) =>
    id ? (catalog.roles.find((item) => item.id === id)?.name ?? id) : "";
  return (
    <div className="seat-list">
      {seats.map((seat) => {
        const card =
          seat.cards?.find((item) => item.alive) ?? seat.cards?.[0] ?? null;
        const witch = Boolean(card?.witch && seat.alive);
        return (
          <article
            key={seat.id}
            className={`seat ${seat.id === state?.self.seat_id ? "own-seat" : ""} ${!seat.alive ? "dead-seat" : ""} ${witch ? "witch-seat" : ""}`}
          >
            <span className="seat-number">{seat.id.padStart(2, "0")}</span>
            <Avatar
              name={seat.id}
              roleId={seat.avatar_role_id}
              previousRoleId={seat.previous_role_id}
              onClick={
                seat.avatar_role_id
                  ? () => onRole(seat.avatar_role_id!)
                  : undefined
              }
            />
            <div className="seat-info">
              <strong>
                {seat.occupied ? seat.name : "等待入席"}
                {seat.avatar_role_id && `（${roleName(seat.avatar_role_id)}）`}
                {seat.id === state?.self.seat_id && <small>你</small>}
              </strong>
              <span>
                {!seat.occupied
                  ? "尚无操作者"
                  : state?.status === "lobby"
                    ? seat.ready
                      ? "已准备"
                      : seat.id === state?.self.seat_id
                        ? state.phase === "lobby"
                          ? "等待准备"
                          : "选择双牌中"
                        : "已入席"
                    : seat.alive
                      ? "存活"
                      : "已出局"}
                {seat.occupied && ` · ${seat.online ? "在线" : "离线"}`}
                {witch && <em className="witch-mark"> · 魔女化预定</em>}
              </span>
              {onInspect && seat.occupied && (
                <button
                  className="quiet tiny"
                  onClick={() => onInspect(seat.id)}
                >
                  视角
                </button>
              )}
            </div>
          </article>
        );
      })}
      {state?.self.honoka_upper && (
        <div className="honoka-roster">
          <h3>已准备玩家的上层角色 · 仅你看得到</h3>
          <ul>
            {state.self.honoka_upper.map((item) => (
              <li key={item.seat_id}>
                {item.seat_id}号 {item.name} · {roleName(item.role_id)}
              </li>
            ))}
          </ul>
          <small>
            只显示文字角色名；若你选择在下层登场，这些信息仍然有效。
          </small>
        </div>
      )}
    </div>
  );
}

function PublicTable({
  onRole,
  onNewGame,
  onInspect,
}: {
  onRole: (id: string) => void;
  onNewGame: () => void;
  onInspect?: (id: string) => void;
}) {
  const { state, session } = useGame();
  if (!state) return null;
  return (
    <>
      <div className="section-heading">
        <h2>{state.status === "ended" ? "终幕 · 对局结算" : "公共桌面"}</h2>
        <span className="tag">全体可见</span>
      </div>
      {state.result && (
        <section className="result-panel">
          <span className="eyebrow">这一页故事，已写下结局</span>
          <h2>
            {state.result.winner === "aborted" ? (
              "本局已终止"
            ) : (
              <>
                <RecordView value={state.result.winner} />
                获胜
              </>
            )}
          </h2>
          <>
            <p>{state.result.reason}</p>
            {!!state.result.personal_results?.length && (
              <section>
                <h3>角色特殊结局</h3>
                <RecordView value={state.result.personal_results} />
              </section>
            )}
          </>
          {!!state.result.personal_losses?.length && (
            <>
              <h3>特殊个人结局</h3>
              <RecordView value={state.result.personal_losses} />
            </>
          )}
          {session.actor?.kind === "host" && (
            <button className="primary" onClick={onNewGame}>
              确认新魔典 · 开启下一局
            </button>
          )}
          <p className="hint">
            本局记录只读，未获准的信息不会因结局自动公开。开启下一局时本局记录会一并清空，但 QQ 登录保持有效；需要保留记录请先截图或抄录。
          </p>
        </section>
      )}
      {state.status === "lobby" && (
        <div className="lobby-note">
          <span className="eyebrow">
            随机入席 → 首次准备 → 私下排牌 → 再次准备 → 主持人开局
          </span>
          <h3>{state.ready_count} / 7 位玩家已准备</h3>
          <p>
            {state.phase === "lobby"
              ? "还未发牌。请在「行动」中点击准备发牌；七人首次准备齐全后，系统才会私下发放双牌。"
              : "双牌已私下发放。请在「行动」中选择上层角色，再次准备；换序会取消本次准备。开局前所有公开角色头像均隐藏。"}
          </p>
          <progress
            value={state.ready_count}
            max={7}
            aria-label="玩家准备进度"
          />
        </div>
      )}
      <div className="table-seats">
        <SeatList seats={state.seats} onRole={onRole} onInspect={onInspect} />
      </div>
      {Object.entries(state.public)
        .filter(([key]) => key !== "current_actor")
        .map(([key, value]) => (
          <section className="public-record" key={key}>
            <h3>{labelFor(key)}</h3>
            <RecordView value={value} />
          </section>
        ))}
      {!Object.keys(state.public).length && (
        <p className="hint">
          当前尚无公开行动记录。主持人公布的投票、热气球、声明与结算会显示在这里。
        </p>
      )}
    </>
  );
}

function PrivatePanel({ onRole }: { onRole: (id: string) => void }) {
  const { state, session, catalog } = useGame();
  if (!state) return null;
  const isHost = session.actor?.kind === "host";
  return (
    <>
      <div className="section-heading">
        <h2>
          {isHost
            ? "主持人私密资料"
            : session.actor?.kind === "spectator"
              ? "获准信息"
              : "我的双角色"}
        </h2>
        <span className="tag gold">
          {session.actor?.kind === "spectator" ? "公开" : "私密"}
        </span>
      </div>
      {session.actor?.kind === "spectator" && (
        <p className="hint">
          观战者不占玩家席位，不获得角色牌。接管席位须由主持人明确授权。
        </p>
      )}
      {session.actor?.kind === "player" && state.phase === "lobby" && (
        <p className="hint">等待七位玩家首次准备，之后在这里查看自己的双牌。</p>
      )}
      {session.actor?.kind === "player" && state.self.seat_id && (
        <p className="hint">
          你在 {seatLabel(state, state.self.seat_id)} 席 · 目前公开显示为「
          {roleLabel(
            catalog,
            state.seats.find((seat) => seat.id === state.self.seat_id)
              ?.avatar_role_id ?? "",
          )}
          」（若你选择在下层登场，公开身份会随登场更新）
        </p>
      )}
      <div className="private-cards">
        {state.self.cards.map((card, index) => (
          <RoleCard
            key={card.id}
            card={card}
            layer={`${index === 0 ? "上层" : "下层"}${card.id === state.self.current_card_id ? " · 当前使用" : ""}`}
            onRole={onRole}
          />
        ))}
      </div>
      {isHost && state.host && (
        <>
          <Codex />
          <details className="record-section" open>
            <summary>本夜预结算</summary>
            <RecordView value={state.host.night_preview} />
          </details>
          <details className="record-section">
            <summary>可用时间快照</summary>
            <RecordView value={state.host.snapshots} />
          </details>
          <HostSources />
        </>
      )}
      {session.actor?.kind === "player" && (
        <section className="public-record">
          <h3>我的行动状态 · 仅自己可见</h3>
          {state.self.water && <p className="tag gold">持有本局唯一13水</p>}
          {state.half === "night" && (
            <>
              <p>
                {state.self.night_confirmed
                  ? "本夜行动已确认"
                  : "本夜尚未确认行动"}
              </p>
              <RecordView value={state.self.night_actions ?? []} />
            </>
          )}
          {state.self.vote && (
            <p>
              当前选票：
              <RecordView value={state.self.vote} />
            </p>
          )}
          {state.self.balloon_choice && (
            <p>
              热气球选择：
              <RecordView value={state.self.balloon_choice} />
            </p>
          )}
        </section>
      )}
      <div className="section-heading information-heading">
        <h2>{isHost ? "信息与证物" : "我的信息与证物"}</h2>
        <span className="count">{state.information.length}</span>
      </div>
      {state.information.length ? (
        [...state.information].reverse().map((item) => (
          <article className="information-card" key={item.id}>
            <h3>{item.title}</h3>
            <p>{item.text}</p>
            {item.image_id && <Evidence id={item.image_id} />}
          </article>
        ))
      ) : (
        <p className="hint">
          尚无获准查看的线索。照片、画作和名单由规则与主持人决定接收范围。
        </p>
      )}
    </>
  );
}

const taskLabels: Record<string, string> = {
  pending: "待裁决",
  night: "夜间未确认",
  speech: "发言",
  nomination: "提名",
  voting: "投票",
  execution: "处决",
  balloon: "热气球",
  review: "阶段推进",
  advance: "阶段推进",
  winner: "胜利宣判",
  surrender: "交牌审阅",
};

function HostTasks({
  onPick,
  onWarn,
}: {
  onPick: (
    id: string,
    payload?: Record<string, unknown>,
    values?: Record<string, unknown>,
  ) => void;
  onWarn: (seatId: string) => void;
}) {
  const { state } = useGame();
  const tasks = state?.host?.tasks ?? [];
  const blocking = tasks.filter((item) => item.blocking).length;
  const goto: Record<string, string> = {
    pending: "前往裁决",
    night: "前往警告",
    speech: "前往警告",
    nomination: "前往警告",
    voting: "前往警告",
    execution: "前往警告",
    balloon: "前往警告",
    review: "前往推进",
    advance: "前往推进",
    winner: "前往宣判",
    surrender: "前往审阅",
  };
  return (
    <section className="pending-panel">
      <div className="section-heading">
        <h2>主持人待办</h2>
        <span className={`count ${blocking ? "gold" : ""}`}>
          {tasks.length}
        </span>
      </div>
      {tasks.length ? (
        tasks.map((task) => (
          <article
            className={`pending-item ${task.blocking ? "blocking" : ""}`}
            key={task.id}
          >
            <div className="split">
              <h3>{task.title}</h3>
              <span className="tag">{taskLabels[task.kind] ?? "待办"}</span>
            </div>
            {task.detail && <p>{task.detail}</p>}
            {Boolean(task.seats.length) && (
              <p className="hint">涉及席位：{task.seats.join("、")}</p>
            )}
            {task.action &&
              (task.action === "host.warn" && task.seats.length ? (
                <button
                  className="primary"
                  onClick={() => onWarn(task.seats[0])}
                >
                  警告30秒
                </button>
              ) : (
                <button
                  className="primary"
                  onClick={() => onPick(task.action!, task.payload)}
                >
                  {goto[task.kind] ?? "前往处理"}
                </button>
              ))}
          </article>
        ))
      ) : (
        <p className="hint">
          没有待办。明确规则由服务器执行；需要你决定的事项会列于此处，玩家未完成操作前不会推进阶段。
        </p>
      )}
    </section>
  );
}

function NightLedger({ onWarn }: { onWarn: (seatId: string) => void }) {
  const { state, catalog } = useGame();
  const host = state?.host;
  if (
    !state ||
    !host ||
    state.status !== "playing" ||
    (state.phase !== "night" && state.phase !== "night_coco")
  ) {
    return null;
  }
  const confirmed = new Set(host.night_confirmed);
  const outstanding = new Set(
    (host.tasks ?? [])
      .filter((task) => task.kind === "night")
      .map((task) => task.seats[0]),
  );
  const rows = state.seats.filter(
    (seat) =>
      seat.occupied &&
      (seat.cards?.some((card) => card.alive) ||
        host.night_actions.some((action) => action.seat_id === seat.id)),
  );
  return (
    <section className="pending-panel">
      <div className="section-heading">
        <h2>本夜全员行动</h2>
        <span className="count gold">
          {rows.filter((seat) => confirmed.has(seat.id)).length} / {rows.length}{" "}
          已确认
        </span>
      </div>
      <p className="hint">
        仅主持人可见。玩家提交后立即显示；未提交即按放弃处理，玩家之间看不到彼此的夜间行动。
      </p>
      <div className="seat-list">
        {rows.map((seat) => {
          const card =
            seat.cards?.find((item) => item.alive) ?? seat.cards?.[0];
          const actions = host.night_actions.filter(
            (action) => action.seat_id === seat.id,
          );
          const done = confirmed.has(seat.id);
          return (
            <article className="seat" key={seat.id}>
              <span className="seat-number">{seat.id.padStart(2, "0")}</span>
              <div className="seat-info">
                <strong>
                  {seat.name}
                  {card && (
                    <small className={card.witch ? "witch-text" : ""}>
                      <RecordView value={card.role_id} />
                      {card.witch ? " · 魔女化" : ""}
                    </small>
                  )}
                </strong>
                {actions.length ? (
                  actions.map((action) => (
                    <span key={action.id}>
                      <RecordView value={action.ability} />
                      {action.target_seat
                        ? ` → ${seatLabel(state, action.target_seat)}（${roleLabel(catalog, currentRoleId(state, action.target_seat))}）`
                        : ""}
                      {typeof action.roll === "number"
                        ? ` · 掷骰 ${action.roll}/${action.denominator}${action.hit ? " 命中" : " 未命中"}`
                        : ""}
                      {typeof action.correct === "number"
                        ? ` · 猜对 ${action.correct}/${state.host?.codex?.length ?? 0}`
                        : ""}
                      {action.image_id && <Evidence id={action.image_id} />}
                      {action.effective === false ? " · 被中毒抵消" : ""}
                      {action.by_host ? " · 主持人代提交" : ""}
                      {action.confirmed ? "" : " · 未确认"}
                    </span>
                  ))
                ) : (
                  <span>{done ? "本夜未发动行动（已确认）" : "尚未提交"}</span>
                )}
                {!done && outstanding.has(seat.id) && (
                  <button
                    className="quiet tiny"
                    onClick={() => onWarn(seat.id)}
                  >
                    警告30秒
                  </button>
                )}
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}

function roleLabel(
  catalog: { roles: { id: string; name: string }[] },
  id: string,
) {
  return catalog.roles.find((item) => item.id === id)?.name ?? id;
}

function HostSources() {
  const { state, catalog } = useGame();
  const host = state?.host;
  if (!state || !host) return null;
  const seatName = (id: string | undefined) =>
    id ? seatLabel(state, id) : "—";
  const declarations = host.declarations ?? [];
  const nominations = host.nominations ?? [];
  const voteRounds = host.vote_rounds ?? [];
  const photos = host.photos ?? [];
  const balloon = host.balloon_choices ?? {};
  const proposal = host.balloon_proposal ?? null;
  const brainwash = host.brainwash ?? {};
  const water = host.water;
  const warnings = host.warnings ?? {};
  const votes = host.votes ?? {};
  const now = Date.now() / 1000;
  return (
    <>
      <details className="record-section" open>
        <summary>技能声明</summary>
        {declarations.length ? (
          <ul className="source-list">
            {declarations.map((item) => (
              <li key={item.id}>
                {item.day}日 · {seatName(item.seat_id)} 声称「
                <RecordView value={item.ability} />」 ·{" "}
                {item.fake ? "伪装" : "真实"} ·{" "}
                <RecordView value={item.status} />
              </li>
            ))}
          </ul>
        ) : (
          <p className="hint">本局尚无技能声明。</p>
        )}
      </details>
      <details className="record-section">
        <summary>提名与投票</summary>
        {nominations.length ? (
          <ul className="source-list">
            {nominations.map((item, index) => (
              <li key={`${item.seat_id}:${index}`}>
                {seatName(item.by)} 提名 {seatName(item.seat_id)}（
                {roleLabel(catalog, item.card_id)}）
              </li>
            ))}
          </ul>
        ) : (
          <p className="hint">尚无提名记录。</p>
        )}
        <p className="hint">
          已提名：
          {host.nomination_done?.length
            ? host.nomination_done.join("、")
            : "无"}
        </p>
        {voteRounds.map((round, index) => (
          <p key={index}>
            第{index + 1}轮 · 候选 {seatName(round.candidate)} · 同意{" "}
            {round.yes}/{round.denominator}（门槛 {round.threshold}）·
            {round.passed ? "通过" : "未通过"}
          </p>
        ))}
        {Boolean(Object.keys(votes).length) && (
          <p>
            当前票型：
            <RecordView value={votes} />
          </p>
        )}
      </details>
      <details className="record-section">
        <summary>热气球</summary>
        <p>
          提交情况：
          <RecordView value={balloon} />
        </p>
        {proposal && (
          <p>
            {proposal.by}号提议名单：
            <RecordView value={proposal} />
          </p>
        )}
        <p>
          结果：
          <RecordView value={state.public.balloon} />
        </p>
      </details>
      <details className="record-section">
        <summary>注视与洗脑</summary>
        <p>
          注视名单：
          <RecordView value={host.gaze} />
        </p>
        <p>
          洗脑：
          <RecordView value={brainwash} />
        </p>
      </details>
      <details className="record-section">
        <summary>13水与警告</summary>
        <p>
          13水持有人：{water?.holder ? seatLabel(state, water.holder) : "无"}
          {water?.used ? "（已使用）" : ""}
        </p>
        {Object.keys(warnings).length ? (
          <ul className="source-list">
            {Object.entries(warnings).map(([id, deadline]) => (
              <li key={id}>
                {seatLabel(state, id)} · 剩余{" "}
                {Math.max(0, Math.ceil(deadline - now))} 秒
              </li>
            ))}
          </ul>
        ) : (
          <p className="hint">当前没有生效中的警告。</p>
        )}
      </details>
      <details className="record-section">
        <summary>照片与画作收发</summary>
        {photos.length ? (
          <ul className="source-list">
            {photos.map((item) => (
              <li key={item.id}>
                {seatName(item.sender)} → {seatName(item.recipient)} ·{" "}
                {item.allowed ? "已送达" : "被拒收"}
                {item.text ? ` · ${item.text}` : ""}
                {item.image_id && <Evidence id={item.image_id} />}
              </li>
            ))}
          </ul>
        ) : (
          <p className="hint">尚无照片或画作往来。</p>
        )}
      </details>
    </>
  );
}

function SeatInspector({ seatId }: { seatId: string }) {
  const { state } = useGame();
  const [data, setData] = useState<SeatView | null>(null);
  const [request, setRequest] = useState<PanelRequest | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const version = state?.version;
  useEffect(() => {
    if (!state) return;
    let cancelled = false;
    setLoading(true);
    api<SeatView>(`/games/${state.id}/seats/${seatId}/view`)
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((failure) => {
        if (!cancelled) setError(errorText(failure));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [state, seatId, version]);
  return (
    <>
      <p className="hint">
        这里显示 {seatId}{" "}
        号玩家自己看到的界面。代操作只能以该席位可用的行动提交，操作内容不会向其他玩家公开，仅留下「主持人代为处理」的公开提示。
      </p>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {loading && !data && <p className="hint">正在读取该席位视角…</p>}
      {data && (
        <div className="inspector">
          <SeatViewCard
            view={data.view}
            onAct={(item) =>
              setRequest({
                id: item.id,
                payload: item.payload,
                token: Date.now(),
              })
            }
          />
          <ActionPanel
            actions={data.view.actions}
            title={`代替操作（${seatId}号）`}
            asSeat={seatId}
            request={request}
            onRequestHandled={() => setRequest(null)}
          />
        </div>
      )}
    </>
  );
}

function SeatViewCard({
  view,
  onAct,
}: {
  view: GameView;
  onAct: (action: UIAction) => void;
}) {
  const { catalog } = useGame();
  return (
    <section className="public-record">
      <div className="section-heading">
        <h2>
          {view.self.seat_id ? seatLabel(view, view.self.seat_id) : "该席位"}
        </h2>
        <span className="tag">{view.phase_label}</span>
      </div>
      <div className="private-cards">
        {view.self.cards.map((card, index) => (
          <div
            className={`mini-card ${card.alive ? "" : "dead-seat"}`}
            key={card.id}
          >
            <small>
              {index === 0 ? "上层" : "下层"}
              {card.id === view.self.current_card_id ? " · 当前使用" : ""}
            </small>
            <strong>{roleLabel(catalog, card.role_id)}</strong>
            <small>
              {card.witch ? "魔女化" : "普通"}
              {card.alive ? "" : " · 出局"}
              {card.injured ? " · 负伤" : ""}
            </small>
          </div>
        ))}
      </div>
      {view.self.warning_deadline ? (
        <Countdown deadline={view.self.warning_deadline} label="该席位被警告" />
      ) : null}
      <h3>该席位当前可提交的操作</h3>
      {view.actions.length ? (
        <ul className="impersonate-list">
          {view.actions.map((item) => (
            <li key={item.id}>
              <span>{item.label}</span>
              <button className="quiet" onClick={() => onAct(item)}>
                代替操作
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="hint">当前没有轮到该席位提交的操作。</p>
      )}
      {view.self.honoka_upper && (
        <>
          <h3>穗乃香可见的上层角色</h3>
          <ul className="source-list">
            {view.self.honoka_upper.map((item) => (
              <li key={item.seat_id}>
                {item.seat_id}号 {item.name} ·{" "}
                {roleLabel(catalog, item.role_id)}
              </li>
            ))}
          </ul>
        </>
      )}
      <h3>仅发给他/她的信息</h3>
      {view.information.length ? (
        view.information.map((item) => (
          <article className="information-card" key={item.id}>
            <h3>{item.title}</h3>
            <p>{item.text}</p>
            {item.image_id && <Evidence id={item.image_id} />}
          </article>
        ))
      ) : (
        <p className="hint">目前没有只发给该席位的裁定或线索。</p>
      )}
    </section>
  );
}

function Codex() {
  const { state, catalog } = useGame();
  return (
    <section className="codex-record">
      <h3>本局魔典 · 私密顺序</h3>
      <ol>
        {state?.host?.codex.map((id, index) => (
          <li key={id}>
            <span>{String(index + 1).padStart(2, "0")}</span>
            {catalog.roles.find((role) => role.id === id)?.name ?? id}
          </li>
        ))}
      </ol>
    </section>
  );
}

function HostManagement({
  onRole,
  onInspect,
}: {
  onRole: (id: string) => void;
  onInspect?: (id: string) => void;
}) {
  const { state, session, catalog, refresh } = useGame();
  const [error, setError] = useState("");
  const [resetOpen, setResetOpen] = useState(false);
  const [resetBusy, setResetBusy] = useState(false);
  if (!state || session.actor?.kind !== "host") return null;
  const reset = async () => {
    setResetBusy(true);
    setError("");
    try {
      await api<Session>("/reset", {});
      setResetOpen(false);
      await refresh();
    } catch (failure) {
      setResetOpen(false);
      setError(errorText(failure));
    } finally {
      setResetBusy(false);
    }
  };
  return (
    <div className="management-content">
      <div className="section-heading">
        <h2>七席参与与双牌</h2>
        <span className="tag gold">仅主持人可见</span>
      </div>
      <p className="hint">
        主持人开放加入后，已登录账号可直接选择玩家或观战，无需审核。发牌后更换玩家仍从观战者中接管原席，不重发牌或重置技能。
      </p>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="invite-grid">
        {state.seats.map((seat) => (
          <article className="invite-seat" key={seat.id}>
            <div className="split">
              <h3>
                {seat.id}号席 · {seat.occupied ? seat.name : "等待入席"}
              </h3>
              <span className="tag">
                {seat.occupied ? (seat.online ? "在线" : "离线") : "空席"}
              </span>
              {onInspect && seat.occupied && (
                <button
                  className="quiet tiny"
                  onClick={() => onInspect(seat.id)}
                >
                  视角
                </button>
              )}
            </div>
            <div className="invite-pair">
              {seat.cards?.map((card, index) => (
                <button key={card.id} onClick={() => onRole(card.role_id)}>
                  <Avatar
                    roleId={card.role_id}
                    name={
                      catalog.roles.find((role) => role.id === card.role_id)
                        ?.name ?? card.role_id
                    }
                  />
                  <span>
                    <small>
                      {index === 0 ? "上层" : "下层"} ·{" "}
                      {card.alive ? "存活" : "出局"}
                    </small>
                    <strong>
                      {catalog.roles.find((role) => role.id === card.role_id)
                        ?.name ?? card.role_id}
                    </strong>
                    <small>
                      {card.witch ? "魔女" : "普通"}
                      {card.injured && " · 负伤"}
                    </small>
                  </span>
                </button>
              ))}
            </div>
            <details>
              <summary>双牌状态与剩余次数</summary>
              {seat.cards?.map((card, index) => (
                <p className="hint" key={card.id}>
                  {index === 0 ? "上层" : "下层"} ·{" "}
                  {roleLabel(catalog, card.role_id)} · 剩余次数：
                  <RecordView value={card.uses} />
                </p>
              ))}
            </details>
          </article>
        ))}
      </div>
      <section className="spectator-invite">
        <h3>主动参局与替补</h3>
        <p className="hint">
          “开放加入”由下方房间管理操作控制。玩家满席或发牌后，登录账号仍可选择观战；需要替补时再由主持人分配现有空席。
        </p>
      </section>
      <Codex />
      <details className="record-section">
        <summary>本局成员与在线状态</summary>
        <RecordView value={state.host?.participants} />
      </details>
      <ActionPanel
        title="房间管理操作"
        actions={state.actions.filter((action) =>
          action.id.startsWith("room."),
        )}
      />
      <section className="spectator-invite">
        <h3>初始化</h3>
        <p className="hint">
          清除全部对局数据：玩家与观战参与身份、取牌与阶段进度、聊天记录、证物图片。删除后无法恢复；QQ 账号、登录令牌和主持人登录保留。
        </p>
        <button
          className="danger-button"
          disabled={resetBusy}
          onClick={() => setResetOpen(true)}
        >
          一键初始化
        </button>
      </section>
      {resetOpen && (
        <Modal
          title="确认清空全部对局数据"
          onClose={() => {
            if (!resetBusy) setResetOpen(false);
          }}
        >
          <p>
            将删除本局的一切数据：七席玩家与观战参与身份、双牌与阶段进度、聊天记录、证物图片。
          </p>
          <p className="hint">
            删除后无法恢复，参与身份会失效；QQ 账号、玩家登录令牌和主持人登录保留，可直接建立下一局。
          </p>
          <div className="button-row">
            <button
              className="primary"
              disabled={resetBusy}
              onClick={() => void reset()}
            >
              {resetBusy ? "清除中…" : "确认清除并回到初始状态"}
            </button>
            <button
              className="quiet"
              disabled={resetBusy}
              onClick={() => setResetOpen(false)}
            >
              取消
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
