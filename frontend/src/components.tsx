import { useEffect, useRef, type ReactNode } from "react";
import { evidenceUrl } from "./api";
import { useGame } from "./state";
import type { Card } from "./types";

export function Modal({
  title,
  children,
  onClose,
  wide = false,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current!;
    dialog.showModal();
    return () => dialog.close();
  }, []);
  return (
    <dialog
      ref={ref}
      className={wide ? "modal wide" : "modal"}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="modal-head">
        <h2>{title}</h2>
        <button className="quiet" onClick={onClose} aria-label="关闭窗口">
          关闭 ×
        </button>
      </div>
      <div className="modal-body">{children}</div>
    </dialog>
  );
}

export function Avatar({
  roleId,
  name,
  host = false,
  onClick,
}: {
  roleId?: string | null;
  name: string;
  host?: boolean;
  onClick?: () => void;
}) {
  const { catalog } = useGame();
  const role = catalog.roles.find((item) => item.id === roleId);
  const image = host ? "/assets/characters/月代雪.png" : role?.avatar;
  const content = image ? (
    <img
      src={image}
      alt={host ? "主持人月代雪" : `${role?.name ?? name}公开头像`}
      loading="lazy"
    />
  ) : (
    <span aria-label={`${name}文字头像`}>
      {roleId === "honoka" ? "穗" : name.slice(0, 1) || "席"}
    </span>
  );
  return onClick ? (
    <button
      className="avatar"
      type="button"
      aria-label={`查看${role?.name ?? name}的角色说明`}
      onClick={onClick}
    >
      {content}
    </button>
  ) : (
    <span className="avatar">{content}</span>
  );
}

export function RoleCard({
  card,
  layer,
  onRole,
}: {
  card: Card;
  layer: string;
  onRole: (id: string) => void;
}) {
  const { catalog } = useGame();
  const role = catalog.roles.find((item) => item.id === card.role_id);
  return (
    <article className={`role-card ${!card.alive ? "fallen" : ""}`}>
      <div className="card-art">
        {role?.avatar ? (
          <img src={role.avatar} alt={`${role.name}角色立绘`} loading="lazy" />
        ) : (
          <span className="honoka-art">穗</span>
        )}
        <span className="layer-tag">{layer}</span>
      </div>
      <div className="card-copy">
        <div className="split">
          <h3>{role?.name ?? card.role_id}</h3>
          <span className={card.witch ? "tag witch" : "tag"}>
            {card.witch ? "魔女" : "普通"}
          </span>
        </div>
        <div className="tags">
          <span className={!card.alive ? "tag danger" : "tag"}>
            {card.alive ? "存活" : "已出局"}
          </span>
          {card.injured && <span className="tag danger">负伤</span>}
        </div>
        {card.states && <RecordView value={card.states} />}
        {card.uses && (
          <div>
            <h4>技能使用记录</h4>
            <RecordView value={card.uses} />
          </div>
        )}
        <button className="text-button" onClick={() => onRole(card.role_id)}>
          阅读角色技能 →
        </button>
      </div>
    </article>
  );
}

const labels: Record<string, string> = {
  id: "编号",
  title: "标题",
  label: "说明",
  name: "名称",
  text: "内容",
  description: "说明",
  reason: "原因",
  seat_id: "席位",
  seat: "席位",
  participant_id: "参与者",
  participant_ids: "接收者",
  occupant_id: "操作者",
  role_id: "角色",
  card_id: "角色牌",
  target: "目标",
  targets: "目标",
  target_id: "目标",
  target_seat: "目标席位",
  target_seat_id: "目标席位",
  target_card_id: "目标角色牌",
  alive: "存活",
  witch: "魔女化",
  injured: "负伤",
  poisoned: "中毒",
  puppet: "傀儡",
  master: "主人",
  protected: "庇护",
  uses: "技能记录",
  states: "状态",
  current_card_id: "当前角色牌",
  cards: "双角色牌",
  ready: "已准备",
  online: "在线",
  occupied: "已入席",
  day: "游戏日",
  half: "日夜",
  phase: "阶段",
  phase_label: "阶段",
  status: "状态",
  confirmed: "已确认",
  resolved: "已结算",
  speaker: "当前发言",
  speaking_order: "发言顺序",
  order: "顺序",
  progress: "进度",
  balloon: "热气球",
  votes: "投票",
  voting: "投票",
  organizer: "组织者",
  organizer_seat: "组织者",
  participants: "参与者",
  invited: "邀请名单",
  choices: "选择",
  candidate: "候选",
  candidates: "候选人",
  ballots: "选票",
  yes: "同意",
  no: "不同意",
  abstain: "弃票",
  threshold: "通过门槛",
  denominator: "有投票权人数",
  eligible: "具备资格",
  passed: "通过",
  passed_candidates: "通过候选",
  codex: "魔典",
  pending: "裁决待办",
  night_actions: "夜间行动",
  snapshots: "时间快照",
  declarations: "公开技能声明",
  action: "行动",
  ability: "技能",
  kind: "类型",
  source: "来源",
  source_id: "来源",
  submitted: "已提交",
  payload: "行动详情",
  outcome: "结果",
  result: "结果",
  winner: "获胜方",
  personal_losses: "特殊落败",
  roll: "抽签结果",
  hit: "命中",
  probability: "概率",
  damage: "伤害",
  deaths: "出局",
  attacks: "攻击",
  effects: "效果",
  protection: "庇护",
  preview: "预结算",
  resolution: "结算",
  image_id: "证物编号",
  audience: "可见对象",
  created_at: "记录时间",
  date: "时间",
  timestamp: "时间",
  water: "13水",
  water_holder: "13水持有者",
  holder: "持有者",
  used: "已使用",
  remaining: "剩余",
  bullets: "剩余子弹",
  poisoned_until: "中毒期限",
  forced_abstain: "强制弃票",
  can_vote: "可以投票",
  vote_lost: "失去投票权",
  binding: "绑定",
  bound: "已绑定",
  madness: "疯狂要求",
  madness_target: "疯狂目标",
  gaze: "注视目标",
  surrendered: "交牌请求",
  surrender: "交牌",
  warnings: "警告",
  deadline: "截止时间",
  muted: "已禁言",
  checked: "已检查",
  active: "生效中",
  public: "公开",
  private: "私密",
  note: "备注",
  notes: "备注",
  snapshot_id: "快照",
  normal: "普通",
  rewind_good: "好人回溯",
  rewind_witch: "魔女回溯",
  emma: "艾玛技能",
  hanna: "汉娜技能",
  meruru: "梅露露技能",
  noah: "诺亚技能",
  annan: "安安技能",
  millia: "米莉亚技能",
  marg: "玛格技能",
  leia: "蕾雅技能",
  enabled: "已开启",
  cancelled: "已取消",
  revoked: "已撤销",
  access_ids: "可继承历史身份",
  share_history: "继承私密历史",
  keep_actions: "保留已提交行动",
  speech_order: "发言顺序",
  nominations: "提名记录",
  by: "提名人",
  round: "轮次",
  total: "轮数",
  results: "计票结果",
  execution_seats: "待处决席位",
  achievements_enabled: "本局成就可用",
  rewinds: "回溯次数",
  interrupted_speaker: "被打断的发言席位",
  night_confirmed: "已确认行动席位",
  night_preview: "本夜预结算",
  balloon_choices: "秘密制作选择",
  balloon_votes: "组织热气球投票",
  brainwash: "洗脑目标",
  spiritual: "精神系与不可回溯效果",
  winner_candidate: "待确认胜负",
  surrenders: "交牌意向席位",
  target_card: "目标角色牌",
  source_card: "真凶角色牌",
  cause: "出局原因",
  effective: "效果生效",
  follow_seat: "目标跟随席位",
  hiro_used: "希罗已使用的回溯",
  hiro_exception: "希罗疯狂例外夜已用",
  sherry_bound: "雪莉与汉娜已绑定",
  annan_penalty: "安安大招次日处罚",
  persistent_states: "回溯保留状态",
  personal_results: "特殊个人结局",
  won: "获胜",
  paintings: "已保存画作",
  paint_done: "完成作画的游戏日",
  no_vote: "无投票权",
  learned_brainwash: "已学会洗脑",
  evidence_allowed: "可提交证物",
  evidence_used: "已提交证物",
  entry_allowed: "本阶段可使用角色技能",
  witness_role: "目击名单显示身份",
  madness_target_seat: "疯狂目标席位",
  puppet_master_seat: "傀儡主人席位",
  extra_kill: "额外攻击已使用",
  swap: "交换已使用",
  frame: "替代真凶已使用",
  decode: "解典已用次数",
  revive: "复活已使用",
  mass_brainwash: "全场洗脑已使用",
  interrupt_day: "打断发言使用日",
  love_day: "爱上目标的游戏日",
  gaze_day: "注视使用日",
  kills: "造成的出局",
  mode: "身份状态",
  expected_day: "对应游戏日",
  expected_phase: "对应阶段",
  victim: "夜间死者",
  death_id: "出局记录",
  declaration_id: "声明编号",
  fake: "伪装技能",
  executed: "效果已执行",
  data: "提交内容",
  keep_states: "额外保留状态",
  confirm: "确认",
  omit_leia: "蕾雅不列入名单",
  true_source: "补充真凶",
  blocked: "本局已拉黑",
  sender: "发送席位",
  recipient: "接收席位",
  allowed: "已获授权",
  guess: "猜测排列",
  night_day: "生效夜晚",
  half_exits: "本半天已出局席位",
  follow: "目标跟随方式",
  allow: "允许",
  persistent: "回溯保留",
  effect: "效果",
  roles: "角色顺序",
  top: "上层角色",
  avatar: "示人头像",
  role: "角色",
  choice: "选择",
  proceed: "继续结算",
  penalty: "不利裁定",
  side: "阵营",
  agree: "同意",
};
const words: Record<string, string> = {
  day: "白天",
  night: "夜晚",
  lobby: "候场",
  playing: "进行中",
  ended: "已结束",
  host: "主持人",
  player: "玩家",
  spectator: "观战者",
  good: "好人",
  witch: "魔女",
  yes: "同意",
  no: "不同意",
  abstain: "弃票",
  build: "制作",
  make: "制作",
  sabotage: "破坏",
  break: "破坏",
  pending: "待裁决",
  confirmed: "已确认",
  skipped: "已放弃",
  skip: "已放弃",
  execution: "处决",
  knife: "魔女刀",
  aborted: "终止对局",
  idle: "尚未开始",
  collecting: "等待选择",
  complete: "已完成",
  open: "可质疑",
  stopped: "已停止",
  night_coco: "夜间最后行动",
  night_review: "夜间预结算",
  night_results: "夜间结果",
  speech: "顺序发言",
  discussion: "自由发言",
  balloon: "热气球",
  nomination: "同时提名",
  voting: "投票",
  dusk: "天黑前结算",
  paint: "作画",
  shoot: "开枪",
  spear: "长矛攻击",
  protect: "庇护",
  swap: "临死交换",
  frame: "替代真凶",
  decode: "破译魔典",
  extra_kill: "额外攻击",
  massacre: "全场攻击",
  interrupt: "打断发言",
  last_speaker: "最后发言",
  love: "爱上目标",
  gaze: "注视",
  brainwash: "秘密洗脑",
  mass_brainwash: "全场洗脑",
  photo: "赠送照片",
  normal: "普通状态",
  injury: "负伤",
  unconditional: "无条件出局",
  death: "出局",
  water: "13水",
  devotion: "殉情",
  challenge: "质疑",
  voluntary: "主动出局",
  card: "跟随角色牌",
  seat: "跟随原席位",
  good_vote: "好人组织投票",
  makers: "制作人数",
  breakers: "破坏席位",
  unsubmitted: "未提交席位",
  delta: "本次增量",
  correct: "猜对数",
  progress: "当前进度",
  last: "上次结算",
  nominate: "提名",
  pass: "放弃提名",
};
export function labelFor(key: string): string {
  return labels[key] ?? key;
}

export function RecordView({
  value,
  depth = 0,
}: {
  value: unknown;
  depth?: number;
}) {
  const { catalog, state } = useGame();
  if (value === null || value === undefined)
    return <span className="muted">无</span>;
  if (typeof value === "boolean") return <span>{value ? "是" : "否"}</span>;
  if (typeof value === "string") {
    const role = catalog.roles.find((item) => item.id === value);
    const card =
      state?.seats
        .flatMap((seat) => seat.cards ?? [])
        .find((item) => item.id === value) ??
      state?.self.cards.find((item) => item.id === value);
    return (
      <span className="record-text">
        {role?.name ??
          (card
            ? catalog.roles.find((item) => item.id === card.role_id)?.name
            : undefined) ??
          words[value] ??
          value}
      </span>
    );
  }
  if (typeof value === "number") return <span>{value}</span>;
  if (Array.isArray(value))
    return value.length ? (
      <ul className={`record-list depth-${Math.min(depth, 2)}`}>
        {value.map((item, index) => (
          <li key={index}>
            <RecordView value={item} depth={depth + 1} />
          </li>
        ))}
      </ul>
    ) : (
      <span className="muted">暂无记录</span>
    );
  if (typeof value === "object") {
    const entries = Object.entries(value);
    return entries.length ? (
      <dl className="record">
        {entries.map(([key, item]) => (
          <div key={key}>
            <dt>{labelFor(key)}</dt>
            <dd>
              <RecordView value={item} depth={depth + 1} />
            </dd>
          </div>
        ))}
      </dl>
    ) : (
      <span className="muted">暂无记录</span>
    );
  }
  return null;
}

export function Evidence({ id }: { id: string }) {
  const { state } = useGame();
  if (!state) return null;
  const url = evidenceUrl(state.id, id);
  return (
    <a className="evidence-link" href={url} target="_blank" rel="noreferrer">
      <img
        src={url}
        alt="获准查看的证物，点击打开原件"
        loading="lazy"
        onError={(event) => {
          event.currentTarget.style.display = "none";
        }}
      />
      <span>打开证物原件 ↗</span>
    </a>
  );
}
