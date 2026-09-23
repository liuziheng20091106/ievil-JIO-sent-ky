import { useEffect, useMemo, useState, type FormEvent } from "react";
import { errorText } from "./api";
import { Drawing } from "./Drawing";
import { draftKey, useDraft } from "./drafts";
import { Modal, RecordView } from "./components";
import { useGame } from "./state";
import type { Catalog, Field, GameView, UIAction } from "./types";

const groups: Record<string, string> = {
  lobby: "候场准备",
  night: "夜间行动",
  day: "白天行动",
  host: "主持人裁决",
  room: "房间管理",
  management: "房间管理",
  pending: "待办裁决",
  vote: "提名与投票",
  voting: "提名与投票",
  information: "私密信息",
  phase: "阶段控制",
  abilities: "角色技能",
};
const fieldTypes: Record<Field["type"], true> = {
  text: true,
  textarea: true,
  number: true,
  select: true,
  multiselect: true,
  checkbox: true,
  drawing: true,
};

function actionIdentity(action: UIAction) {
  return JSON.stringify(
    [action.id, action.payload ?? {}],
    (_key, value: unknown) =>
      value && typeof value === "object" && !Array.isArray(value)
        ? Object.fromEntries(
            Object.entries(value).sort(([a], [b]) => a.localeCompare(b)),
          )
        : value,
  );
}
export type PanelRequest = {
  id: string;
  payload?: Record<string, unknown>;
  values?: Record<string, unknown>;
  token: number;
};
export function ActionPanel({
  actions,
  title = "本阶段行动",
  asSeat,
  request,
  onRequestHandled,
  onOpenChange,
}: {
  actions: UIAction[];
  title?: string;
  asSeat?: string;
  request?: PanelRequest | null;
  onRequestHandled?: () => void;
  onOpenChange?: (open: boolean) => void;
}) {
  const { state, session } = useGame();
  const supported =
    state?.ui_version === 1 &&
    actions.every(
      (action) =>
        [...action.short_label].length >= 2 &&
        [...action.short_label].length <= 4 &&
        action.fields.every((field) => fieldTypes[field.type]),
    );
  const [selected, setSelected] = useState<{
    action: UIAction;
    version: number;
    key: string;
    actorId: string | undefined;
    gameId: string;
    asSeat?: string;
    values?: Record<string, unknown>;
  } | null>(null);
  const [query, setQuery] = useState("");
  const select = (action: UIAction, values?: Record<string, unknown>) => {
    if (!state) return;
    setSelected({
      action,
      version: state.version,
      key: draftKey(
        state.id,
        session.actor?.id ?? null,
        "action",
        state.day,
        state.half,
        state.phase,
        actionIdentity(action),
        // 主持人代操作按席位分草稿，避免跨席位串改预填内容。
        asSeat ?? null,
      ),
      actorId: session.actor?.id,
      gameId: state.id,
      asSeat,
      values,
    });
  };
  const open = Boolean(selected);
  useEffect(() => onOpenChange?.(open), [open, onOpenChange]);
  const requestToken = request?.token;
  useEffect(() => {
    if (!request) return;
    const match = actions.find(
      (action) =>
        action.id === request.id &&
        Object.entries(request.payload ?? {}).every(
          ([name, value]) => action.payload?.[name] === value,
        ),
    );
    if (match) select(match, request.values);
    onRequestHandled?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestToken]);
  const grouped = useMemo(() => {
    const result = new Map<string, UIAction[]>();
    actions
      .filter((action) =>
        `${action.label} ${action.description ?? ""} ${action.group ?? ""}`.includes(
          query,
        ),
      )
      .forEach((action) => {
        const group = groups[action.group ?? ""] ?? action.group ?? "可用操作";
        result.set(group, [...(result.get(group) ?? []), action]);
      });
    return result;
  }, [actions, query]);
  if (!supported)
    return (
      <section className="actions-section">
        <p className="error" role="alert">
          客户端版本不支持当前行动，请升级后再提交。
        </p>
      </section>
    );
  return (
    <section className="actions-section">
      <div className="section-heading">
        <h2>{title}</h2>
        <span className="count">{actions.length}</span>
      </div>
      {actions.length > 8 && (
        <input
          className="action-search"
          type="search"
          aria-label="查找行动"
          placeholder="查找技能、裁决或管理操作"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      )}
      {!actions.length && (
        <div className="empty compact">
          <span className="ornament">—</span>
          <p>当前没有需要提交的操作</p>
          <small>等待其他玩家或主持人推进阶段。掉线不会自动放弃行动。</small>
        </div>
      )}
      {actions.length > 0 && !grouped.size && (
        <p className="hint">没有匹配的操作。</p>
      )}
      {[...grouped].map(([group, items]) => (
        <details className="action-group" key={group} open>
          <summary>
            {group}
            <span>{items.length}</span>
          </summary>
          <div className="action-grid">
            {items.map((action, index) => (
              <button
                className={`action-tile ${action.danger ? "danger-action" : ""}`}
                key={`${action.id}:${index}`}
                title={action.description || action.label}
                onClick={() => select(action)}
              >
                <span>{action.short_label}</span>
                <span className="arrow" aria-hidden="true">
                  ↗
                </span>
              </button>
            ))}
          </div>
        </details>
      ))}
      {selected &&
        selected.actorId === session.actor?.id &&
        selected.gameId === state?.id && (
          <ActionForm
            key={selected.key}
            storageKey={selected.key}
            action={selected.action}
            version={selected.version}
            asSeat={selected.asSeat}
            initial={selected.values}
            onClose={() => setSelected(null)}
          />
        )}
    </section>
  );
}

function initialValue(field: Field): unknown {
  if (field.default !== undefined) return field.default;
  if (field.type === "checkbox") return false;
  if (field.type === "multiselect") return [];
  return "";
}
function ActionForm({
  action,
  version,
  onClose,
  storageKey,
  asSeat,
  initial,
}: {
  action: UIAction;
  version: number;
  onClose: () => void;
  storageKey: string;
  asSeat?: string;
  initial?: Record<string, unknown>;
}) {
  const { command, busy, state, session, catalog } = useGame();
  const isHost = session.actor?.kind === "host";
  const [expectedVersion, setExpectedVersion] = useState(version);
  const [descriptor, setDescriptor] = useState(action);
  action = descriptor;
  const [savedValues, setValues, clearDraft, draftError] = useDraft<
    Record<string, unknown>
  >(storageKey, () =>
    Object.fromEntries(
      action.fields
        .filter((field) => field.name !== "confirm")
        .map((field) => [
          field.name,
          initial?.[field.name] ?? initialValue(field),
        ]),
    ),
  );
  // 外部明确预填的值（如主持人30秒警告的目标席位）优先于本键旧草稿的恢复值。
  const mergedValues =
    initial == null
      ? savedValues
      : (() => {
          const next = { ...savedValues };
          for (const field of action.fields)
            if (initial[field.name] !== undefined)
              next[field.name] = initial[field.name];
          return next;
        })();
  const [confirmed, setConfirmed] = useState(false);
  const values = action.fields.some((field) => field.name === "confirm")
    ? { ...mergedValues, confirm: confirmed }
    : mergedValues;
  const [error, setError] = useState("");
  const update = (name: string, value: unknown) => {
    if (name === "confirm") setConfirmed(Boolean(value));
    else setValues((previous) => ({ ...previous, [name]: value }));
    setError("");
  };
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    // 单次确认：校验通过后直接提交，不再进入二次确认步骤。
    {
      for (const field of action.fields) {
        const value = values[field.name];
        if (
          field.required &&
          (value === "" ||
            value === null ||
            value === undefined ||
            (Array.isArray(value) && !value.length) ||
            (field.type === "checkbox" && !value))
        ) {
          setError(`请完成「${field.label}」。`);
          return;
        }
        if (
          field.options &&
          (Array.isArray(value)
            ? value
            : value === "" || value == null
              ? []
              : [value]
          ).some(
            (item) => !field.options!.some((option) => option.value === item),
          )
        ) {
          setError(`「${field.label}」的选项已失效，请重新选择。`);
          return;
        }
        if (
          field.type === "multiselect" &&
          Array.isArray(value) &&
          ((field.min !== undefined && value.length < field.min) ||
            (field.max !== undefined && value.length > field.max))
        ) {
          setError(
            `「${field.label}」请选择${field.min ?? 0}至${field.max ?? "不限"}项。`,
          );
          return;
        }
      }
    }
    const payload = { ...values };
    delete payload.confirm;
    for (const field of action.fields) {
      if (field.type === "number") {
        if (payload[field.name] === "") {
          delete payload[field.name];
        } else payload[field.name] = Number(payload[field.name]);
      }
      if (field.type === "drawing") {
        delete payload[field.name];
        if (values[field.name]) payload.image = values[field.name];
      }
    }
    try {
      await command(action, payload, expectedVersion, asSeat);
      clearDraft();
      onClose();
    } catch (failure) {
      setError(errorText(failure));
      setConfirmed(false);
    }
  };
  const stale = state?.version !== expectedVersion;
  const latestAction = [
    ...(state?.actions ?? []),
    ...(state?.channels?.flatMap((channel) => channel.actions ?? []) ?? []),
    ...(state?.self.puppet_controls?.flatMap((panel) => panel.actions) ?? []),
  ].find((item) => actionIdentity(item) === actionIdentity(action));
  const selectedTop =
    action.id === "lobby.order"
      ? state?.self.cards.find((card) => card.id === values.top)
      : undefined;
  const selectedBottom = selectedTop
    ? state?.self.cards.find((card) => card.id !== selectedTop.id)
    : undefined;
  return (
    <Modal
      title={action.label}
      onClose={() => {
        if (!busy) onClose();
      }}
      wide={action.fields.some((field) => field.type === "drawing")}
    >
      {action.description && (
        <p className="form-description">{action.description}</p>
      )}
      {action.danger && (
        <p className="warning">
          此操作涉及出局、结算或房间权限。请核对目标和影响后确认。
        </p>
      )}
      {stale && (
        <div className="warning">
          <p>
            对局状态已更新。已填写内容和画作仍保留，请按最新状态重新核对目标。
          </p>
          {latestAction ? (
            <button
              type="button"
              className="secondary"
              disabled={busy}
              onClick={() => {
                setExpectedVersion(state!.version);
                setDescriptor(latestAction);
                setConfirmed(false);
                setError("");
              }}
            >
              保留填写，核对最新状态
            </button>
          ) : (
            <p>当前操作已结束或不可用，请关闭窗口选择其他行动。</p>
          )}
        </div>
      )}
      <form onSubmit={(event) => void submit(event)}>
        {action.fields.map((field) => (
          <ActionField
            key={field.name}
            field={field}
            value={values[field.name]}
            onChange={(value) => update(field.name, value)}
          />
        ))}
        {selectedTop && selectedBottom && (
          <p className="hint" role="status">
            上层：
            {catalog.roles.find((role) => role.id === selectedTop.role_id)
              ?.name ?? selectedTop.role_id}
            ；下层已自动选择：
            {catalog.roles.find((role) => role.id === selectedBottom.role_id)
              ?.name ?? selectedBottom.role_id}
            。
          </p>
        )}
        {action.id === "room.replace" && (
          <section className="warning">
            <h4>接管将继承以下席位状态</h4>
            <RecordView
              value={state?.seats.find(
                (seat) =>
                  seat.id ===
                  String(values.seat_id ?? action.payload?.seat_id),
              )}
            />
            <h4>当前已提交行动（是否保留以上方选择为准）</h4>
            <RecordView value={state?.host?.night_actions} />
            <p>原操作者将失去此席位权限；私密历史仅按你选择的范围授予。</p>
          </section>
        )}
        {action.fields.length === 0 && (
          <p className="hint">
            将执行「{action.label}」。结果及可见范围由服务器按规则处理。
          </p>
        )}
        {draftError && (
          <p className="warning" role="alert">
            {draftError}
          </p>
        )}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <div className="form-footer">
          <button
            type="submit"
            className={action.danger ? "danger-button" : "primary"}
            disabled={busy || stale}
          >
            {busy ? "正在提交…" : "确认提交"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function seatChoiceLabel(
  option: { value: string; label: string },
  state: GameView | null,
  catalog: Catalog,
  isHost: boolean,
) {
  const seat = state?.seats.find((item) => item.id === option.value);
  if (!seat) return option.label;
  const cards = seat.cards ?? [];
  if (state?.status === "lobby") return `${seat.id}号 · ${seat.name}`;
  if (isHost) {
    const names = [...new Set(cards.map((card) => card.role_id))].map(
      (roleId) => catalog.roles.find((role) => role.id === roleId)?.name ?? roleId,
    );
    return names.length
      ? `${seat.id}号 · ${seat.name}（${names.join("／")}）`
      : option.label;
  }
  // 只展示该视图已获准的公开头像：没有可见信息的位置一律显示 ?，不从隐藏卡补全。
  const publicIds = [seat.previous_role_id, seat.avatar_role_id].filter(
    (roleId): roleId is string => Boolean(roleId),
  );
  const names = publicIds.length
    ? publicIds.map(
        (roleId) =>
          catalog.roles.find((role) => role.id === roleId)?.name ?? roleId,
      )
    : ["?"];
  return `${seat.id}号 · ${seat.name}（${names.join("→")}）`;
}

function ActionField({
  field,
  value,
  onChange,
}: {
  field: Field;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const { state, session, catalog } = useGame();
  const id = `field-${field.name}`;
  const options = useMemo(
    () =>
      field.options?.map((option) => ({
        ...option,
        label: seatChoiceLabel(
          option,
          state,
          catalog,
          session.actor?.kind === "host",
        ),
      })) ?? [],
    [field.options, state, catalog, session.actor?.kind],
  );
  if (field.type === "checkbox")
    return (
      <label className="check-row">
        <input
          id={id}
          type="checkbox"
          checked={Boolean(value)}
          required={field.required}
          onChange={(event) => onChange(event.target.checked)}
        />
        <span>
          {field.label}
          {field.required && "（必选）"}
        </span>
      </label>
    );
  if (field.type === "drawing")
    return (
      <fieldset className="field">
        <legend>
          {field.label}
          {field.required && " *"}
        </legend>
        <Drawing
          value={String(value || "")}
          onChange={onChange}
          label={field.label}
        />
      </fieldset>
    );
  if (field.type === "multiselect") {
    const selected = Array.isArray(value) ? value.map(String) : [];
    return (
      <fieldset className="field">
        <legend>
          {field.label}
          {field.required && " *"}
        </legend>
        <p className="hint">
          已选{selected.length}项
          {field.max !== undefined && `，最多${field.max}项`}
          。需要顺序时，按下方编号排列。
        </p>
        <div className="multiselect">
          {options.map((option) => (
            <label
              className={`check-row ${selected.includes(option.value) ? "selected" : ""}`}
              key={option.value}
            >
              <input
                type="checkbox"
                checked={selected.includes(option.value)}
                disabled={
                  !selected.includes(option.value) &&
                  field.max !== undefined &&
                  selected.length >= field.max
                }
                onChange={(event) =>
                  onChange(
                    event.target.checked
                      ? [...selected, option.value]
                      : selected.filter((item) => item !== option.value),
                  )
                }
              />
              <span>{option.label}</span>
            </label>
          ))}
        </div>
        {selected.length > 1 && (
          <ol className="selected-order">
            {selected.map((item, index) => (
              <li key={item}>
                <span>
                  {options.find((option) => option.value === item)?.label ??
                    item}
                </span>
                <button
                  type="button"
                  className="quiet"
                  aria-label={`将第${index + 1}项上移`}
                  disabled={index === 0}
                  onClick={() => {
                    const order = [...selected];
                    [order[index - 1], order[index]] = [
                      order[index],
                      order[index - 1],
                    ];
                    onChange(order);
                  }}
                >
                  ↑
                </button>
                <button
                  type="button"
                  className="quiet"
                  aria-label={`将第${index + 1}项下移`}
                  disabled={index === selected.length - 1}
                  onClick={() => {
                    const order = [...selected];
                    [order[index], order[index + 1]] = [
                      order[index + 1],
                      order[index],
                    ];
                    onChange(order);
                  }}
                >
                  ↓
                </button>
              </li>
            ))}
          </ol>
        )}
      </fieldset>
    );
  }
  return (
    <label className="field" htmlFor={id}>
      <span>
        {field.label}
        {field.required && " *"}
      </span>
      {field.type === "select" ? (
        <select
          id={id}
          required={field.required}
          value={String(value ?? "")}
          onChange={(event) => onChange(event.target.value)}
        >
          <option value="">请选择</option>
          {options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      ) : field.type === "textarea" ? (
        <textarea
          id={id}
          required={field.required}
          value={String(value ?? "")}
          rows={4}
          onChange={(event) => onChange(event.target.value)}
        />
      ) : (
        <input
          id={id}
          type={field.type === "number" ? "number" : "text"}
          required={field.required}
          value={String(value ?? "")}
          min={field.min}
          max={field.max}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
    </label>
  );
}
