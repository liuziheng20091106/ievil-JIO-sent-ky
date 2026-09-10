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
  const [connection, setConnection] = useState<Connection>("connecting");
  const latest = useRef(0);
  const room = useRef<string | null>(null);
  const mutation = useRef(false);
  const mergeMessages = useCallback((items: Message[]) => {
    for (const item of items)
      latest.current = Math.max(latest.current, item.id);
    setMessages((previous) =>
      [
        ...new Map(
          [...previous, ...items].map((item) => [item.id, item]),
        ).values(),
      ].sort((a, b) => a.id - b.id),
    );
  }, []);
  const acceptState = useCallback((next: GameView) => {
    setState((previous) =>
      previous?.id === next.id && previous.version > next.version
        ? previous
        : next,
    );
  }, []);
  const adoptSession = useCallback(
    async (next: Session) => {
      if (room.current !== next.game_id) {
        room.current = next.game_id;
        latest.current = 0;
        setMessages([]);
        setState(null);
      }
      setSession(next);
      if (next.actor && next.game_id) {
        acceptState(await api<GameView>(`/games/${next.game_id}/state`));
      }
    },
    [acceptState],
  );
  const refresh = useCallback(async () => {
    try {
      const [nextCatalog, nextSession] = await Promise.all([
        api<Catalog>("/catalog"),
        api<Session>("/me"),
      ]);
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
    const catchUp = async (after: number) => {
      try {
        let cursor = after;
        while (active) {
          const page = await api<MessagePage>(
            `/games/${gameId}/messages?after=${cursor}`,
          );
          if (!active) return;
          mergeMessages(page.messages);
          const nextCursor = Math.max(
            cursor,
            ...page.messages.map((message) => message.id),
          );
          if (!page.has_more || nextCursor === cursor) return;
          cursor = nextCursor;
        }
      } catch (failure) {
        if (active) setError(errorText(failure));
      }
    };
    const disconnect = connectLive(
      (event) => {
        if (!active) return;
        if (event.type === "sync") {
          const cursor = latest.current;
          acceptState(event.state);
          mergeMessages(event.messages);
          if (cursor) void catchUp(cursor);
        } else if (event.type === "state") acceptState(event.state);
        else if (event.type === "message") mergeMessages([event.message]);
      },
      (status) => {
        if (!active) return;
        setConnection(status);
        if (status === "unauthorized") {
          setError("会话已失效或席位已变更，请重新进入。");
          setSession(emptySession);
          setState(null);
          setMessages([]);
          latest.current = 0;
          room.current = null;
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
    await api("/logout", {});
    room.current = null;
    latest.current = 0;
    setSession(emptySession);
    setState(null);
    setMessages([]);
    setError("");
  };
  const create = async (codex: string[]) => {
    const next = await api<GameView>("/games", { codex });
    room.current = next.id;
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
    try {
      acceptState(
        await api<GameView>(`/games/${state.id}/commands`, {
          expected_version: version,
          action: action.id,
          payload: { ...action.payload, ...payload },
        }),
      );
      setError("");
    } catch (failure) {
      // A lost response may already have committed; refresh, never replay a mutation.
      try {
        acceptState(await api<GameView>(`/games/${state.id}/state`));
      } catch (refreshFailure) {
        setError(errorText(refreshFailure));
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
        error,
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
