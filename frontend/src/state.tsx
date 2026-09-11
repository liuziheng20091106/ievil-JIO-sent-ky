import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { api, ApiError, errorText } from "./api";
import { connectLive } from "./live";
import { clearActorDrafts } from "./drafts";
import type {
  Catalog,
  Connection,
  GameView,
  Message,
  MessagePage,
  Session,
  UIAction,
} from "./types";

interface GameContext {
  catalog: Catalog;
  session: Session;
  state: GameView | null;
  messages: Message[];
  loading: boolean;
  error: string;
  connection: Connection;
  busy: boolean;
  setError: (text: string) => void;
  authenticate: (path: string, body: unknown) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
  create: (codex: string[]) => Promise<void>;
  command: (
    action: UIAction,
    payload: Record<string, unknown>,
    version: number,
  ) => Promise<void>;
  mergeMessages: (messages: Message[]) => void;
}
const Context = createContext<GameContext | null>(null);
const emptySession: Session = { actor: null, game_id: null };

export function GameProvider({ children }: { children: ReactNode }) {
  const [catalog, setCatalog] = useState<Catalog>({
    roles: [],
    default_codex: [],
  });
  const [session, setSession] = useState<Session>(emptySession);
  const [state, setState] = useState<GameView | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [draftError, setDraftError] = useState("");
  const [connection, setConnection] = useState<Connection>("connecting");
  const latest = useRef(0);
  const actor = useRef<Session["actor"]>(null);
  const scope = JSON.stringify([session.game_id, session.actor?.id ?? null]);
  const identity = useRef(scope);
  const mutation = useRef(false);
  const mergeMessages = useCallback((items: Message[]) => {
    if (identity.current !== scope) return;
    for (const item of items)
      latest.current = Math.max(latest.current, item.id);
    setMessages((previous) =>
      [
        ...new Map(
          [...previous, ...items].map((item) => [item.id, item]),
        ).values(),
      ].sort((a, b) => a.id - b.id),
    );
  }, [scope]);
  const acceptState = useCallback((next: GameView, owner: string) => {
    if (identity.current !== owner) return;
    setState((previous) =>
      previous?.id === next.id && previous.version > next.version
        ? previous
        : next,
    );
  }, []);
  const adoptSession = useCallback(
    async (next: Session) => {
      const owner = JSON.stringify([next.game_id, next.actor?.id ?? null]);
      if (identity.current !== owner) {
        if (actor.current && actor.current.id !== next.actor?.id)
          setDraftError(clearActorDrafts(actor.current.id));
        identity.current = owner;
        actor.current = next.actor;
        latest.current = 0;
        setMessages([]);
        setState(null);
      }
      setSession(next);
      if (next.actor && next.game_id) {
        acceptState(await api<GameView>(`/games/${next.game_id}/state`), owner);
      }
    },
    [acceptState],
  );
  const refresh = useCallback(async () => {
    const owner = identity.current;
    try {
      const [nextCatalog, nextSession] = await Promise.all([
        api<Catalog>("/catalog"),
        api<Session>("/me"),
      ]);
      if (identity.current !== owner) return;
      setCatalog(nextCatalog);
      await adoptSession(nextSession);
      setError("");
    } catch (failure) {
      setError(errorText(failure));
    } finally {
      setLoading(false);
    }
  }, [adoptSession]);
  useEffect(() => {
    void refresh();
  }, [refresh]);
  useEffect(() => {
    if (!session.actor || !state) return;
    if (
      session.game_id !== state.id ||
      (session.actor.kind !== "host" &&
        session.actor.seat_id !== state.self.seat_id)
    )
      void refresh();
  }, [session.actor, session.game_id, state?.id, state?.self.seat_id, refresh]);
  useEffect(() => {
    if (!session.actor || !session.game_id) return;
    let active = true;
    const gameId = session.game_id;
    const owner = identity.current;
    const catchUp = async (after: number) => {
      try {
        let cursor = after;
        while (active) {
          const page = await api<MessagePage>(
            `/games/${gameId}/messages?after=${cursor}`,
          );
          if (!active || identity.current !== owner) return;
          mergeMessages(page.messages);
          const nextCursor = Math.max(
            cursor,
            ...page.messages.map((message) => message.id),
          );
          if (!page.has_more || nextCursor === cursor) return;
          cursor = nextCursor;
        }
      } catch (failure) {
        if (active && identity.current === owner) setError(errorText(failure));
      }
    };
    const disconnect = connectLive(
      (event) => {
        if (!active || identity.current !== owner) return;
        if (event.type === "sync") {
          const cursor = latest.current;
          acceptState(event.state, owner);
          mergeMessages(event.messages);
          if (cursor) void catchUp(cursor);
        } else if (event.type === "state") acceptState(event.state, owner);
        else if (event.type === "message") mergeMessages([event.message]);
      },
      (status) => {
        if (!active || identity.current !== owner) return;
        setConnection(status);
        if (status === "unauthorized") {
          if (actor.current) setDraftError(clearActorDrafts(actor.current.id));
          actor.current = null;
          identity.current = JSON.stringify([null, null]);
          setError("会话已失效或席位已变更，请重新进入。");
          setSession(emptySession);
          setState(null);
          setMessages([]);
          latest.current = 0;
        }
      },
    );
    return () => {
      active = false;
      disconnect();
    };
  }, [session.actor?.id, session.game_id, acceptState, mergeMessages]);
  const authenticate = async (path: string, body: unknown) => {
    await adoptSession(await api<Session>(path, body));
    setError("");
    history.replaceState(null, "", location.pathname);
  };
  const logout = async () => {
    const owner = identity.current;
    await api("/logout", {});
    if (identity.current !== owner) return;
    if (actor.current) setDraftError(clearActorDrafts(actor.current.id));
    actor.current = null;
    identity.current = JSON.stringify([null, null]);
    latest.current = 0;
    setSession(emptySession);
    setState(null);
    setMessages([]);
    setError("");
  };
  const create = async (codex: string[]) => {
    const owner = identity.current;
    const next = await api<GameView>("/games", { codex });
    if (identity.current !== owner) return;
    identity.current = JSON.stringify([next.id, actor.current?.id ?? null]);
    latest.current = 0;
    setMessages([]);
    setState(next);
    setSession((previous) => ({ ...previous, game_id: next.id }));
  };
  const command = async (
    action: UIAction,
    payload: Record<string, unknown>,
    version: number,
  ) => {
    if (!state || mutation.current)
      throw new Error("另一项操作正在提交，请稍候。");
    mutation.current = true;
    setBusy(true);
    const owner = identity.current;
    try {
      acceptState(
        await api<GameView>(`/games/${state.id}/commands`, {
          expected_version: version,
          action: action.id,
          payload: { ...action.payload, ...payload },
        }),
        owner,
      );
      if (identity.current === owner) setError("");
    } catch (failure) {
      if (identity.current !== owner) throw failure;
      // A lost response may already have committed; refresh, never replay a mutation.
      try {
        acceptState(await api<GameView>(`/games/${state.id}/state`), owner);
      } catch (refreshFailure) {
        if (identity.current === owner) setError(errorText(refreshFailure));
      }
      if (failure instanceof ApiError && failure.status === 409)
        throw new Error(
          `${failure.message} 已刷新，请检查最新目标后重新确认。`,
        );
      throw failure;
    } finally {
      mutation.current = false;
      setBusy(false);
    }
  };
  return (
    <Context.Provider
      value={{
        catalog,
        session,
        state,
        messages,
        loading,
        error: error || draftError,
        connection,
        busy,
        setError,
        authenticate,
        logout,
        refresh,
        create,
        command,
        mergeMessages,
      }}
    >
      {children}
    </Context.Provider>
  );
}

export function useGame() {
  const context = useContext(Context);
  if (!context) throw new Error("游戏上下文未加载");
  return context;
}
