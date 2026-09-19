import {
  useSyncExternalStore,
  type Dispatch,
  type SetStateAction,
} from "react";

const prefix = "seven-draft:";
const storageError = "本地草稿未能保存，当前内容仅保留在本页；请勿刷新或关闭。";
let tabId = "";
let tabError = "";
try {
  const navigation = performance.getEntriesByType("navigation")[0] as
    | PerformanceNavigationTiming
    | undefined;
  tabId =
    navigation?.type === "reload" || navigation?.type === "back_forward"
      ? (sessionStorage.getItem(`${prefix}tab`) ?? "")
      : "";
  tabId ||= Array.from(crypto.getRandomValues(new Uint32Array(4)), (part) =>
    part.toString(16),
  ).join("-");
  sessionStorage.setItem(`${prefix}tab`, tabId);
} catch {
  tabError = storageError;
}
const namespace = `${prefix}${tabId}:`;

type Snapshot = { value: unknown; error: string; revision: number };
type Draft = {
  snapshot: Snapshot;
  initial: unknown;
  listeners: Set<() => void>;
  active: boolean;
};
const drafts = new Map<string, Draft>();

export function draftKey(
  gameId: string | null,
  actorId: string | null,
  ...parts: unknown[]
) {
  return JSON.stringify([gameId, actorId, ...parts]);
}

function notify(draft: Draft) {
  for (const listener of draft.listeners) listener();
}

export function useDraft<T>(
  key: string,
  initial: T | (() => T),
): readonly [T, Dispatch<SetStateAction<T>>, () => void, string] {
  let draft = drafts.get(key);
  if (!draft) {
    const fallback =
      typeof initial === "function" ? (initial as () => T)() : initial;
    let value = fallback;
    let error = tabError;
    try {
      if (tabError) throw new Error(tabError);
      const stored = localStorage.getItem(namespace + key);
      if (stored !== null) {
        const parsed: unknown = JSON.parse(stored);
        if (!parsed || typeof parsed !== "object" || !("value" in parsed))
          throw new Error("草稿损坏");
        const saved = parsed.value;
        if (
          (saved === null) !== (fallback === null) ||
          typeof saved !== typeof fallback ||
          Array.isArray(saved) !== Array.isArray(fallback)
        )
          throw new Error("草稿格式不符");
        value = saved as T;
      }
    } catch {
      error =
        "本地草稿无法恢复或存储不可用；当前填写仅保留在本页，请勿刷新或关闭。";
    }
    draft = {
      snapshot: { value, error, revision: 0 },
      initial: fallback,
      listeners: new Set(),
      active: true,
    };
    drafts.set(key, draft);
  }
  const entry = draft;
  const snapshot = useSyncExternalStore(
    (listener) => {
      entry.listeners.add(listener);
      return () => {
        entry.listeners.delete(listener);
      };
    },
    () => entry.snapshot,
  );
  const setValue: Dispatch<SetStateAction<T>> = (update) => {
    if (!entry.active) return;
    const value =
      typeof update === "function"
        ? (update as (previous: T) => T)(entry.snapshot.value as T)
        : update;
    if (Object.is(value, entry.snapshot.value)) return;
    let error = "";
    try {
      if (tabError) throw new Error(tabError);
      localStorage.setItem(namespace + key, JSON.stringify({ value }));
    } catch {
      error = storageError;
    }
    entry.snapshot = { value, error, revision: entry.snapshot.revision + 1 };
    notify(entry);
  };
  // A successful old request must not erase edits made after its render.
  const clear = () => {
    if (!entry.active || entry.snapshot.revision !== snapshot.revision) return;
    let error = "";
    try {
      if (tabError) throw new Error(tabError);
      localStorage.removeItem(namespace + key);
    } catch {
      error = "已提交，但本地草稿未能清除；刷新后请先核对记录，勿重复提交。";
    }
    entry.snapshot = {
      value: error ? snapshot.value : entry.initial,
      error,
      revision: snapshot.revision + 1,
    };
    notify(entry);
    if (error) throw new Error(error);
  };
  return [snapshot.value as T, setValue, clear, snapshot.error] as const;
}

export function clearDraftKey(key: string) {
  const draft = drafts.get(key);
  if (draft) {
    draft.active = false;
    draft.snapshot = {
      value: draft.initial,
      error: "",
      revision: draft.snapshot.revision + 1,
    };
    notify(draft);
    drafts.delete(key);
  }
  try {
    if (!tabError) localStorage.removeItem(namespace + key);
  } catch {
    // 删除失败无碍：新键会重建草稿。
  }
}

export function clearActorDrafts(actorId: string): string {
  const belongsToActor = (key: string) => {
    try {
      const parts: unknown = JSON.parse(key);
      return Array.isArray(parts) && parts[1] === actorId;
    } catch {
      return false;
    }
  };
  for (const [key, draft] of drafts) {
    if (!belongsToActor(key)) continue;
    draft.active = false;
    draft.snapshot = {
      value: draft.initial,
      error: "",
      revision: draft.snapshot.revision + 1,
    };
    notify(draft);
    drafts.delete(key);
  }
  try {
    if (tabError) throw new Error(tabError);
    const keys: string[] = [];
    for (let index = 0; index < localStorage.length; index++) {
      const key = localStorage.key(index);
      if (
        key?.startsWith(namespace) &&
        belongsToActor(key.slice(namespace.length))
      )
        keys.push(key);
    }
    for (const key of keys) localStorage.removeItem(key);
    return "";
  } catch {
    return "本地私密草稿未能清除；请在离开共用设备前清除此站点的浏览器存储。";
  }
}
