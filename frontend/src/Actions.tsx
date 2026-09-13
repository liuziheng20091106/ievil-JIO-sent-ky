import { useEffect, useMemo, useState, type FormEvent } from "react";
import { errorText } from "./api";
import { Drawing } from "./Drawing";
import { draftKey, useDraft } from "./drafts";
import { Modal, RecordView } from "./components";
import { useGame } from "./state";
import type { Field, UIAction } from "./types";

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
  balloon: "热气球",
  information: "私密信息",
  phase: "阶段控制",
  abilities: "角色技能",
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
}: {
  actions: UIAction[];
  title?: string;
  asSeat?: string;
  request?: PanelRequest | null;
  onRequestHandled?: () => void;
}) {
  const { state, session } = useGame();
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
      ),
      actorId: session.actor?.id,
      gameId: state.id,
      asSeat,
      values,
    });
  };
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
                onClick={() => select(action)}
              >
                <span>{action.label}</span>
                {action.description && <small>{action.description}</small>}
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
  const { command, busy, state } = useGame();
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
  const [confirmed, setConfirmed] = useState(false);
  const values = action.fields.some((field) => field.name === "confirm")
    ? { ...savedValues, confirm: confirmed }
    : savedValues;
  const [review, setReview] = useState(false);
  const [error, setError] = useState("");
  const update = (name: string, value: unknown) => {
    if (name === "confirm") setConfirmed(Boolean(value));
    else setValues((previous) => ({ ...previous, [name]: value }));
    setError("");
  };
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!review) {
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
      if (!action.instant) {
        setReview(true);
        return;
      }
    }
    const payload = { ...values };
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
      setReview(false);
      setConfirmed(false);
    }
  };
  const stale = state?.version !== expectedVersion;
  const latestAction = state?.actions.find(
    (item) => actionIdentity(item) === actionIdentity(action),
  );
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
                setReview(false);
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
        {!review ? (
          action.fields.map((field) => (
            <ActionField
              key={field.name}
              field={field}
              value={values[field.name]}
              onChange={(value) => update(field.name, value)}
            />
          ))
        ) : (
          <div className="action-review">
            <h3>确认目标与内容</h3>
            {action.fields.length === 0 && (
              <p>
                将执行「{action.label}」。结果及可见范围由服务器按规则处理。
              </p>
            )}
            {action.fields.map((field) => (
              <div key={field.name}>
                <h4>{field.label}</h4>
                {field.type === "drawing" && values[field.name] ? (
                  <img
                    className="drawing-preview"
                    src={String(values[field.name])}
                    alt="即将提交的画作"
                  />
                ) : (
                  <RecordView
                    value={
                      field.options
                        ? Array.isArray(values[field.name])
                          ? (values[field.name] as unknown[]).map(
                              (value) =>
                                field.options?.find(
                                  (option) => option.value === value,
                                )?.label ?? value,
                            )
                          : (field.options.find(
                              (option) => option.value === values[field.name],
                            )?.label ?? values[field.name])
                        : values[field.name]
                    }
                  />
                )}
              </div>
            ))}
            {action.payload && Object.keys(action.payload).length > 0 && (
              <details>
                <summary>操作绑定的对象与选项</summary>
                <RecordView value={action.payload} />
              </details>
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
                <p>原操作者将失去此席位权限；私密历史仅按你确认的范围授予。</p>
              </section>
            )}
          </div>
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
          {review && (
            <button
              type="button"
              className="quiet"
              onClick={() => setReview(false)}
              disabled={busy}
            >
              返回修改
            </button>
          )}
          <button
            type="submit"
            className={action.danger ? "danger-button" : "primary"}
            disabled={busy || stale}
          >
            {busy
              ? "正在提交…"
              : review
                ? "确认提交"
                : action.instant
                  ? "直接提交"
                  : "核对并继续"}
          </button>
        </div>
      </form>
    </Modal>
  );
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
  const id = `field-${field.name}`;
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
          {field.options?.map((option) => (
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
                  {field.options?.find((option) => option.value === item)
                    ?.label ?? item}
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
          {field.options?.map((option) => (
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
