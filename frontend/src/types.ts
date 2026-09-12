export interface Role {
  id: string;
  name: string;
  avatar: string | null;
  normal: string;
  witch: string;
}
export interface Catalog {
  roles: Role[];
  default_codex: string[];
}
export interface Actor {
  id: string;
  kind: "host" | "player" | "spectator";
  game_id: string | null;
  seat_id: string | null;
  name: string;
}
export interface Session {
  actor: Actor | null;
  game_id: string | null;
}
export interface Card {
  id: string;
  role_id: string;
  alive: boolean;
  witch: boolean;
  injured: boolean;
  states?: Record<string, unknown>;
  uses?: Record<string, unknown>;
  [key: string]: unknown;
}
export interface Seat {
  id: string;
  name: string;
  avatar_role_id: string | null;
  occupied: boolean;
  ready: boolean | null;
  alive: boolean;
  online?: boolean;
  cards?: Card[];
}
export interface Field {
  name: string;
  label: string;
  type:
    | "text"
    | "textarea"
    | "number"
    | "select"
    | "multiselect"
    | "checkbox"
    | "drawing";
  required?: boolean;
  options?: { value: string; label: string }[];
  default?: unknown;
  min?: number;
  max?: number;
}
export interface UIAction {
  id: string;
  label: string;
  description?: string;
  group?: string;
  danger?: boolean;
  payload?: Record<string, unknown>;
  fields: Field[];
}
export interface Information {
  id: string;
  title: string;
  text: string;
  image_id?: string;
}
export interface Channel {
  id: string;
  label: string;
  can_send: boolean;
  reason?: string;
}
export interface NightAction {
  id: string;
  seat_id: string;
  card_id: string;
  ability: string;
  target_seat?: string;
  confirmed?: boolean;
  [key: string]: unknown;
}
export interface GameView {
  id: string;
  version: number;
  status: "lobby" | "playing" | "ended";
  day: number;
  half: "day" | "night";
  phase: string;
  phase_label: string;
  deadline: number | null;
  seats: Seat[];
  ready_count: number;
  self: {
    seat_id: string | null;
    cards: Card[];
    current_card_id: string | null;
    night_confirmed?: boolean;
    night_actions?: NightAction[];
    water?: boolean;
    vote?: string | null;
    balloon_choice?: string | null;
    warning_deadline?: number | null;
  };
  actions: UIAction[];
  information: Information[];
  public: Record<string, unknown>;
  host?: {
    codex: string[];
    pending: Record<string, unknown>[];
    night_actions: NightAction[];
    night_confirmed: string[];
    snapshots: Record<string, unknown>[];
    [key: string]: unknown;
  };
  result: null | {
    winner: string;
    reason: string;
    personal_losses?: unknown[];
    personal_results?: unknown[];
  };
  channels?: Channel[];
  can_chat?: boolean;
  chat_reason?: string;
}
export interface Message {
  id: number;
  kind: "chat" | "notice" | "information" | "presence";
  sender_id: string;
  sender_name: string;
  avatar_role_id: string | null;
  channel_id: string;
  text: string;
  created_at: string;
  image_id?: string;
}
export interface MessagePage {
  messages: Message[];
  has_more: boolean;
}
export interface Invite {
  code: string;
  kind: "player" | "spectator";
}
export type LiveEvent =
  | { type: "sync"; state: GameView; messages: Message[] }
  | { type: "state"; state: GameView }
  | { type: "message"; message: Message }
  | { type: "ping" };
export type Connection = "connecting" | "online" | "offline" | "unauthorized";
