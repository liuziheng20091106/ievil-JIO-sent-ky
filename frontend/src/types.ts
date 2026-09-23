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
  account_id?: string;
  kind: "account" | "host" | "player" | "spectator";
  game_id: string | null;
  seat_id: string | null;
  name: string;
  qq_id?: string;
  avatar_url?: string | null;
  access_ids?: string[];
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
  previous_role_id?: string | null;
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
  short_label: string;
  label: string;
  description?: string;
  group?: string;
  danger?: boolean;
  blocking?: boolean;
  payload?: Record<string, unknown>;
  fields: Field[];
  /** 傀儡代操作：动作所属的受控席位。 */
  as_seat?: string | null;
}
export interface PuppetPanel {
  seat_id: string;
  name: string;
  actions: UIAction[];
  /** 该受控席位可见的频道（公开讨论与本人已有私信）。 */
  channels?: Channel[];
}
export interface StatusCard {
  id: string;
  tone: "info" | "success" | "warning" | "danger";
  title: string;
  text: string;
}
export interface PublicDeclaration {
  id: string;
  seat_id: string;
  label: string;
  summary: string;
  status: string;
}
export interface HostTask {
  id: string;
  kind: string;
  title: string;
  detail?: string;
  seats: string[];
  action?: string;
  payload?: Record<string, unknown>;
  blocking?: boolean;
}
export interface CurrentActor {
  phase: string;
  seat_id: string | null;
  label: string;
}
export interface HostDeclaration {
  id: string;
  day: number;
  seat_id: string;
  card_id: string;
  ability: string;
  fake: boolean;
  status: string;
}
export interface HostNomination {
  seat_id: string;
  card_id: string;
  by: string;
}
export interface HostPhoto {
  id: string;
  sender: string;
  target: string;
  day: number;
  allowed: boolean;
}
export interface HostParticipant {
  id: string;
  kind: string;
  seat_id: string | null;
  name: string;
  active: boolean;
  blocked: boolean;
  muted: boolean;
  online: boolean;
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
  status: "pending" | "active" | "ended";
  creator_id?: string;
  members: { id: string; name: string; kind: Actor["kind"] }[];
  invited_ids?: string[];
  accepted_ids?: string[];
  invitation?: "none" | "pending" | "accepted";
  can_send: boolean;
  reason?: string;
  actions?: UIAction[];
  /** 傀儡视角频道：该频道代表受控席位，发送时回传 as_seat。 */
  as_seat?: string | null;
}
export interface NightAction {
  id: string;
  seat_id: string;
  card_id: string;
  ability: string;
  target_seat?: string;
  target_card?: string;
  guess?: string[];
  confirmed?: boolean;
  by_host?: boolean;
  effective?: boolean;
  roll?: number;
  denominator?: number;
  hit?: boolean;
  correct?: number;
  image_id?: string | null;
  [key: string]: unknown;
}
export interface GameView {
  ui_version: number;
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
    warning_deadline?: number | null;
    honoka_upper?: { seat_id: string; name: string; role_id: string }[];
    statuses?: StatusCard[];
    /** 傀儡席的原玩家：只读旁观，由魔女梅露露代为行动。 */
    puppet_spectator?: boolean;
    /** 控制傀儡的魔女梅露露：按受控席位分组的带星号动作。 */
    puppet_controls?: PuppetPanel[];
  };
  actions: UIAction[];
  information: Information[];
  public: {
    current_actor?: CurrentActor;
    auto_advance_at?: number | null;
    auto_advance_off?: boolean;
    declarations?: PublicDeclaration[];
    /** 自由发言结束请求：已提交的席位号。 */
    discussion_end_requests?: string[];
  } & Record<string, unknown>;
  host?: {
    codex: string[];
    pending: Record<string, unknown>[];
    night_actions: NightAction[];
    night_confirmed: string[];
    snapshots: Record<string, unknown>[];
    tasks?: HostTask[];
    declarations?: HostDeclaration[];
    nominations?: HostNomination[];
    nomination_done?: string[];
    speech_passed?: string[];
    vote_rounds?: {
      candidate: string;
      yes: number;
      denominator: number;
      threshold: number;
      passed: boolean;
    }[];
    votes?: Record<string, string>;
    photos?: HostPhoto[];
    brainwash?: Record<string, string>;
    water?: { holders: string[] };
    discussion_end_requests?: string[];
    warnings?: Record<string, number>;
    winner_candidate?: { winner: string; reason: string } | null;
    surrenders?: string[];
    participants?: HostParticipant[];
    night_preview?: unknown;
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
export interface SeatView {
  seat_id: string;
  name: string;
  view: GameView;
}
export interface Message {
  id: number;
  kind: "chat" | "notice" | "information" | "presence" | "alert";
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
export interface LoginChallenge {
  id: string;
  code?: string;
  expires_at: string;
  status: "pending" | "completed";
  session?: Session;
}
export interface LobbyGame {
  id: string;
  status: GameView["status"];
  phase: string;
  join_open: boolean;
  player_seats_available: number;
  can_join_player: boolean;
  can_join_spectator: boolean;
}
export interface Lobby {
  game: LobbyGame | null;
  participation: Actor | null;
}
export type LiveEvent =
  | { type: "sync"; state: GameView; messages: Message[] }
  | { type: "state"; state: GameView }
  | { type: "message"; message: Message }
  | { type: "ping" };
export type Connection = "connecting" | "online" | "offline" | "unauthorized";
