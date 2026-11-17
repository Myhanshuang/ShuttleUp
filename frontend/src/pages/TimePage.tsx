import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import ActivityProgress from "../ActivityProgress";
import { api, ApiError } from "../api/client";
import { useSession } from "../session";
import { addDays, Heading, localDay, send, useAction } from "../ui";
type State = "free" | "busy" | "uncertain" | "unknown";
type Paint = State | "inherit";
type Draft = {
  day: string;
  start: string;
  end: string;
  state: Paint;
  weekly: boolean;
};
const names = {
    free: "空闲",
    busy: "繁忙",
    uncertain: "不确定",
    unknown: "未知（未设置）",
    inherit: "恢复个人时间",
  },
  weekdays = ["日", "一", "二", "三", "四", "五", "六"];
const clock = (slot: number) =>
  `${String(Math.floor(slot / 2)).padStart(2, "0")}:${String(Math.round(slot * 30) % 60).padStart(2, "0")}`;
const stamp = (day: string, time: string) =>
  `${time === "24:00" ? addDays(day, 1) : day}T${time === "24:00" ? "00:00" : time}:00+08:00`;
export default function TimePage() {
  const navigate = useNavigate();
  const [view, setView] = useState<"day" | "week">(() =>
    window.matchMedia("(max-width: 700px)").matches ? "day" : "week",
  );
  const editor = useRef<HTMLFormElement>(null);
  const [editing, setEditing] = useState<number | null>(null),
    [inspected, setInspected] = useState("");
  const ignoreClick = useRef(false);
  const [params] = useSearchParams(),
    activityId = params.get("activity_id"),
    action = useAction();
  const { user } = useSession(),
    generation = useRef(0),
    scroll = useRef<HTMLDivElement>(null);
  const draftKey = `shuttleup-draft:${user?.id}:${activityId || "personal"}`;
  const [restored] = useState(() => {
    try {
      const saved = JSON.parse(sessionStorage.getItem(draftKey) || "{}");
      return {
        drafts: Array.isArray(saved.drafts) ? (saved.drafts as Draft[]) : [],
        scope:
          activityId && saved.scope !== "personal" ? "activity" : "personal",
      };
    } catch {
      return {
        drafts: [] as Draft[],
        scope: activityId ? "activity" : "personal",
      };
    }
  });
  const [week, setWeek] = useState(localDay()),
    [data, setData] = useState<any>({ revision: 0, rules: [], resolved: [] }),
    [loaded, setLoaded] = useState(false);
  const [state, setState] = useState<Paint>("free"),
    [weekly, setWeekly] = useState(false),
    [drafts, setDrafts] = useState<Draft[]>(restored.drafts),
    [selection, setSelection] = useState<{
      day: string;
      start: number;
      end: number;
    } | null>(null);
  const drag = useRef<typeof selection>(null),
    [day, setDay] = useState(localDay()),
    [start, setStart] = useState("18:00"),
    [end, setEnd] = useState("20:00"),
    [scope, setScope] = useState(restored.scope);
  const [share, setShare] = useState(""),
    [preview, setPreview] = useState<any>(null),
    [label, setLabel] = useState("我的课表"),
    [activity, setActivity] = useState<any>(null);
  const days = Array.from({ length: 7 }, (_, n) => addDays(week, n));
  const visibleDays = view === "day" ? [day] : days;
  function moveDate(amount: number) {
    const next = addDays(view === "day" ? day : week, amount);
    setDay(next);
    setWeek(next);
  }
  async function load() {
    const current = ++generation.current;
    const query = new URLSearchParams({
      from_: stamp(week, "00:00"),
      to: stamp(addDays(week, 7), "00:00"),
    });
    if (scope === "activity" && activityId)
      query.set("activity_id", activityId);
    const result = await api(`/me/availability?${query}`);
    if (current !== generation.current) return;
    setData(result);
    setLoaded(true);
  }
  useEffect(() => {
    setLoaded(false);
    void action.run(load);
  }, [week, scope, activityId]);
  useEffect(() => {
    if (activityId)
      void action.run(async () => {
        const a = await api<any>(`/activities/${activityId}`);
        setActivity(a);
        setWeek(a.date_from);
        setDay(a.date_from);
      });
  }, [activityId]);
  useEffect(() => {
    sessionStorage.setItem(draftKey, JSON.stringify({ drafts, scope }));
  }, [drafts, draftKey, scope]);
  useEffect(() => {
    if (loaded && scroll.current) scroll.current.scrollTop = 0;
  }, [loaded]);
  useEffect(() => {
    if (!drafts.length) return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [drafts.length]);
  function matchesDraft(d: Draft, date: string) {
    return (
      d.day === date ||
      (d.weekly &&
        date >= d.day &&
        date <= addDays(d.day, 180) &&
        new Date(stamp(d.day, "12:00")).getDay() ===
          new Date(stamp(date, "12:00")).getDay())
    );
  }
  function add(d: Draft) {
    if (action.pending) return;
    if (d.end <= d.start || d.start < "08:00" || d.end > "22:00") return;
    setDrafts((previous) =>
      editing === null
        ? [...previous, d]
        : previous.map((x, i) => (i === editing ? d : x)),
    );
    setEditing(null);
    setInspected("");
  }
  function stateAt(day: string, slot: number): State {
    const time = new Date(stamp(day, clock(slot))).getTime();
    const priority: Record<string, number> = {
      baseline: 0,
      course: 10,
      weekly: 20,
      one_off: 30,
      activity: 40,
    };
    const saved = data.resolved?.find(
      (s: any) => time >= Date.parse(s.start) && time < Date.parse(s.end),
    );
    let result: State = saved?.state || "unknown",
      rank = priority[saved?.source] ?? -1;
    for (const draft of drafts) {
      const matches = matchesDraft(draft, day);
      const draftRank = scope === "activity" ? 40 : draft.weekly ? 20 : 30;
      if (
        matches &&
        clock(slot) >= draft.start &&
        clock(slot) < draft.end &&
        draftRank >= rank
      ) {
        result =
          draft.state === "inherit"
            ? data.personal_resolved?.find(
                (s: any) =>
                  time >= Date.parse(s.start) && time < Date.parse(s.end),
              )?.state || "unknown"
            : draft.state;
        rank = draftRank;
      }
    }
    return result;
  }

  async function save() {
    const rules = drafts.map((d) =>
      scope === "activity"
        ? {
            source: "activity",
            activity_id: activityId,
            state: d.state,
            kind: "once",
            start_at: stamp(d.day, d.start),
            end_at: stamp(d.day, d.end),
          }
        : d.weekly
          ? {
              source: "weekly",
              state: d.state,
              kind: "weekly",
              recurrence: {
                weekdays: [new Date(stamp(d.day, "12:00")).getUTCDay() || 7],
                start_time: d.start,
                end_time: d.end,
                valid_from: d.day,
                valid_until: addDays(d.day, 180),
                timezone: "Asia/Shanghai",
              },
            }
          : {
              source: "one_off",
              state: d.state,
              kind: "once",
              start_at: stamp(d.day, d.start),
              end_at: stamp(d.day, d.end),
            },
    );
    try {
      await api(
        "/me/availability/rules",
        send({ rules, expected_revision: data.revision }),
      );
    } catch (error) {
      if (error instanceof ApiError && error.code === "VERSION_CONFLICT") {
        await load();
        throw new Error(
          "时间表已在其他入口更新，已刷新底图并保留草稿。请检查后再次保存。",
        );
      }
      throw error;
    }
    setDrafts([]);
    setEditing(null);
    setInspected("");
    await load();
  }
  function sourceAt(d: string, slot: number) {
    const time = Date.parse(stamp(d, clock(slot)));
    const saved = data.resolved?.find(
      (s: any) => time >= Date.parse(s.start) && time < Date.parse(s.end),
    );
    if (scope === "activity" && saved?.source && saved.source !== "activity")
      return "继承个人时间";
    return (
      (
        {
          activity: "本次活动覆盖",
          course: "导入课表",
          weekly: "每周重复",
          one_off: "个人临时时间",
          baseline: "个人基础时间",
        } as Record<string, string>
      )[saved?.source] || "默认未设置"
    );
  }
  function inspect(d: string, slot: number, draftIndex?: number) {
    if (action.pending) return;
    const time = Date.parse(stamp(d, clock(slot)));
    let index = -1;
    drafts.forEach((x, i) => {
      if (matchesDraft(x, d) && clock(slot) >= x.start && clock(slot) < x.end)
        index = i;
    });
    if (draftIndex !== undefined) index = draftIndex;
    const saved = data.resolved?.find(
      (s: any) => time >= Date.parse(s.start) && time < Date.parse(s.end),
    );
    const localClock = (value: string) =>
      new Date(value).toLocaleTimeString("en-GB", {
        timeZone: "Asia/Shanghai",
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      });
    const editDay = index >= 0 ? drafts[index].day : d;
    setDay(editDay);
    if (editDay < week || editDay > days[6]) setWeek(editDay);
    setEditing(index >= 0 ? index : null);
    setStart(
      index >= 0
        ? drafts[index].start
        : saved && Date.parse(saved.start) > Date.parse(stamp(d, "08:00"))
          ? localClock(saved.start)
          : "08:00",
    );
    setEnd(
      index >= 0
        ? drafts[index].end
        : saved && Date.parse(saved.end) < Date.parse(stamp(d, "22:00"))
          ? localClock(saved.end)
          : "22:00",
    );
    setState(index >= 0 ? drafts[index].state : stateAt(d, slot));
    setWeekly(index >= 0 ? drafts[index].weekly : false);
    setInspected(index >= 0 ? "正在编辑待保存时段" : sourceAt(d, slot));
    window.requestAnimationFrame(() => {
      editor.current?.scrollIntoView({ block: "center" });
      editor.current?.focus({ preventScroll: true });
    });
  }
  function tap(d: string, slot: number) {
    if (
      stateAt(d, slot) !== "unknown" ||
      drafts.some(
        (x) =>
          matchesDraft(x, d) && clock(slot) >= x.start && clock(slot) < x.end,
      )
    )
      inspect(d, slot);
    else
      add({
        day: d,
        start: clock(slot),
        end: clock(slot + 1),
        state,
        weekly: weekly && scope === "personal",
      });
  }
  function finishDrag() {
    if (!drag.current) return;
    const d = drag.current;
    ignoreClick.current = true;
    if (d.start === d.end) tap(d.day, d.start);
    else
      add({
        day: d.day,
        start: clock(Math.min(d.start, d.end)),
        end: clock(Math.max(d.start, d.end) + 1),
        state,
        weekly: weekly && scope === "personal",
      });
    drag.current = null;
    setSelection(null);
  }
  const validRange = end > start && start >= "08:00" && end <= "22:00";
  const duration =
    Number(end.slice(0, 2)) * 60 +
    Number(end.slice(3)) -
    (Number(start.slice(0, 2)) * 60 + Number(start.slice(3)));
  return (
    <div className="time-page">
      <Heading
        eyebrow={
          activity
            ? `本次活动：${activity.title}`
            : "把有空的时间，留给喜欢的运动"
        }
        title={
          activity && scope === "activity" ? "本次空闲时间" : "我的空闲时间"
        }
      >
        <span className="badge">北京时间 · UTC+8</span>
      </Heading>
      {activity && (
        <div className="notice">
          正在安排「{activity.title}」 ·{" "}
          <Link to={`/a/${activityId}`}>返回活动</Link>
        </div>
      )}
      {activity && (
        <ActivityProgress
          status={activity.status}
          billingStatus={activity.billing_status}
        />
      )}
      <div className="time-toolbar card">
        <div>
          <h2>标记你何时有空</h2>
          <p className="muted">
            选择状态后点选时间格；电脑可拖选，已有时间块可点开编辑。带斜纹的区域尚未保存。
          </p>
        </div>
        <div className="actions">
          {(["free", "busy", "uncertain"] as State[]).map((s) => (
            <button
              key={s}
              disabled={action.pending}
              aria-pressed={state === s}
              className={`swatch ${s} ${state === s ? "selected" : ""}`}
              onClick={() => setState(s)}
            >
              {names[s]}
            </button>
          ))}
        </div>
        <div className="actions">
          <label>
            作用范围
            <select
              disabled={!!drafts.length || action.pending}
              value={scope}
              onChange={(e) => {
                setScope(e.target.value);
                setEditing(null);
                setInspected("");
                if (state === "inherit") setState("free");
              }}
            >
              <option value="personal">个人时间（用于所有活动）</option>
              {activityId && <option value="activity">仅本次活动</option>}
            </select>
          </label>
          {scope === "personal" && (
            <label className="check">
              <input
                type="checkbox"
                checked={weekly}
                onChange={(e) => setWeekly(e.target.checked)}
              />
              每周重复（从选定日期起 180 天）
            </label>
          )}
        </div>
      </div>
      {action.feedback}
      <div className="calendar-layout">
        <article className="card calendar-card">
          <div className="calendar-navigation">
            <div className="section-head">
              <h2>{view === "day" ? day : `${week} — ${days[6]}`}</h2>
              <div className="segmented">
                <button
                  aria-pressed={view === "day"}
                  className={view === "day" ? "selected" : ""}
                  onClick={() => setView("day")}
                >
                  单日
                </button>
                <button
                  aria-pressed={view === "week"}
                  className={view === "week" ? "selected" : ""}
                  onClick={() => setView("week")}
                >
                  整周
                </button>
              </div>
            </div>
            <div className="date-navigation">
              <button
                aria-label={view === "day" ? "上一天" : "上一周"}
                disabled={action.pending}
                onClick={() => moveDate(view === "day" ? -1 : -7)}
              >
                ←
              </button>
              <button
                onClick={() => {
                  setWeek(localDay());
                  setDay(localDay());
                }}
              >
                今天
              </button>
              <button
                aria-label={view === "day" ? "下一天" : "下一周"}
                disabled={action.pending}
                onClick={() => moveDate(view === "day" ? 1 : 7)}
              >
                →
              </button>
            </div>
            {view === "day" && (
              <div className="day-picker" aria-label="选择日期">
                {days.map((d) => (
                  <button
                    key={d}
                    aria-pressed={d === day}
                    className={d === day ? "selected" : ""}
                    onClick={() => setDay(d)}
                  >
                    <small>
                      周{weekdays[new Date(stamp(d, "12:00")).getDay()]}
                    </small>
                    {d.slice(8)}
                  </button>
                ))}
              </div>
            )}
            {selection && (
              <p className="selection-summary">
                选中 {selection.day}{" "}
                {clock(Math.min(selection.start, selection.end))}–
                {clock(Math.max(selection.start, selection.end) + 1)} ·{" "}
                {(Math.abs(selection.end - selection.start) + 1) * 30} 分钟
              </p>
            )}
          </div>
          {!loaded ? (
            <p role="status">正在读取时间表…</p>
          ) : (
            <div className="calendar-scroll" ref={scroll}>
              <div
                className={`calendar ${view === "day" ? "day-calendar" : ""}`}
                onPointerMove={(e) => {
                  if (!drag.current) return;
                  const rect = scroll.current?.getBoundingClientRect();
                  if (rect && scroll.current) {
                    if (e.clientY > rect.bottom - 28)
                      scroll.current.scrollTop += 16;
                    else if (e.clientY < rect.top + 70)
                      scroll.current.scrollTop -= 16;
                  }
                  const el = document
                    .elementFromPoint(e.clientX, e.clientY)
                    ?.closest<HTMLElement>("[data-slot]");
                  if (el && el.dataset.day === drag.current.day) {
                    drag.current = {
                      ...drag.current,
                      end: Number(el.dataset.slot),
                    };
                    setSelection(drag.current);
                  }
                }}
                onPointerUp={finishDrag}
                onPointerCancel={() => {
                  drag.current = null;
                  setSelection(null);
                }}
              >
                <div className="calendar-corner">时间</div>
                {visibleDays.map((d) => (
                  <div
                    className={`day-heading ${d === localDay() ? "today" : ""}`}
                    key={d}
                  >
                    周{weekdays[new Date(stamp(d, "12:00")).getDay()]}
                    <strong>{d.slice(5)}</strong>
                  </div>
                ))}
                {Array.from({ length: 28 }, (_, index) => index + 16).map(
                  (slot) => (
                    <div className="calendar-row" key={slot}>
                      <div className="time-label">{clock(slot)}</div>
                      {visibleDays.map((d) => {
                        const selected =
                          selection?.day === d &&
                          slot >= Math.min(selection.start, selection.end) &&
                          slot <= Math.max(selection.start, selection.end);
                        const dirty = drafts.some(
                          (x) =>
                            matchesDraft(x, d) &&
                            clock(slot) >= x.start &&
                            clock(slot) < x.end,
                        );
                        const value = stateAt(d, slot);
                        const minuteStates = Array.from(
                          { length: 30 },
                          (_, minute) => stateAt(d, slot + minute / 30),
                        );
                        const mixed = minuteStates.some((s) => s !== value);
                        const runs: { state: State; start: number; end: number }[] = [];
                        minuteStates.forEach((minuteState, minute) => {
                          const last = runs[runs.length - 1];
                          if (last?.state === minuteState) last.end = minute + 1;
                          else runs.push({ state: minuteState, start: minute, end: minute + 1 });
                        });
                        const intervalSummary = runs.map((run) =>
                          `${clock(slot + run.start / 30)}–${clock(slot + run.end / 30)} ${names[run.state]}`,
                        ).join("；");
                        const colors = {
                          free: "var(--mint)",
                          busy: "#f1d9de",
                          uncertain: "var(--uncertain)",
                          unknown: "var(--unknown)",
                        };
                        const gradient = mixed
                          ? `linear-gradient(to bottom, ${minuteStates.map((s, i) => `${colors[s]} ${(i / 30) * 100}% ${((i + 1) / 30) * 100}%`).join(",")})`
                          : undefined;
                        return (
                          <button
                            key={d}
                            disabled={action.pending}
                            data-slot={slot}
                            style={
                              gradient
                                ? {
                                    backgroundImage: dirty
                                      ? `repeating-linear-gradient(135deg,transparent,transparent 5px,#ffffff90 5px,#ffffff90 8px), ${gradient}`
                                      : gradient,
                                  }
                                : undefined
                            }
                            data-day={d}
                            title={intervalSummary}
                            className={`time-cell ${scope === "activity" && sourceAt(d, slot) === "继承个人时间" && !dirty ? "inherited" : ""} ${selected && state !== "inherit" ? state : value} ${dirty ? "draft" : ""} ${selected ? "drawing" : ""}`}
                            aria-label={`${d} ${clock(slot)} ${mixed ? `混合时段 · ${intervalSummary}` : names[value]} · ${dirty ? "待保存" : sourceAt(d, slot)}`}
                            onPointerDown={(e) => {
                              if (e.button !== 0 || e.pointerType === "touch")
                                return;
                              ignoreClick.current = false;
                              e.currentTarget.setPointerCapture(e.pointerId);
                              drag.current = { day: d, start: slot, end: slot };
                              setSelection(drag.current);
                            }}
                            onClick={() => {
                              if (ignoreClick.current) {
                                ignoreClick.current = false;
                                return;
                              }
                              tap(d, slot);
                            }}
                          >
                            {mixed ? runs.filter((run) => run.state !== "unknown" && run.end - run.start >= 20).map((run) => (
                              <span
                                key={run.start}
                                aria-hidden="true"
                                className={`time-segment-label ${run.state}`}
                                style={{ top: `${run.start / 30 * 100}%`, height: `${(run.end - run.start) / 30 * 100}%` }}
                              >{names[run.state]}</span>
                            )) : slot % 2 === 0 && value !== "unknown"
                              ? names[value]
                              : ""}
                            {view === "day" &&
                              !mixed &&
                              slot % 2 === 0 &&
                              value !== "unknown" && (
                                <small>
                                  {dirty ? "待保存" : sourceAt(d, slot)}
                                </small>
                              )}
                          </button>
                        );
                      })}
                    </div>
                  ),
                )}
              </div>
            </div>
          )}
          <p className="muted">
            显示
            08:00–22:00。灰色为未设置，紫蓝色为不确定，两者都不计为空闲。左侧虚线表示继承个人时间。
          </p>
        </article>
        <aside className="stack">
          <form
            ref={editor}
            tabIndex={-1}
            className="card stack time-editor"
            onSubmit={(e) => {
              e.preventDefault();
              add({
                day,
                start,
                end,
                state,
                weekly: weekly && scope === "personal",
              });
            }}
          >
            <h2>{inspected ? "编辑选中时段" : "精确添加时段"}</h2>
            {inspected && (
              <p className="time-source">
                {inspected} ·{" "}
                {scope === "activity" ? "修改仅作用于本次活动" : "修改个人时间"}
                <small>按选定范围覆盖状态，范围外的记录保持不变。</small>
              </p>
            )}
            <label>
              日期
              <input
                type="date"
                required
                value={day}
                onChange={(e) => {
                  setDay(e.target.value);
                  if (e.target.value) setWeek(e.target.value);
                }}
              />
            </label>
            <div className="form-grid">
              <label>
                开始
                <input
                  type="time"
                  min="08:00"
                  max="22:00"
                  required
                  value={start}
                  onChange={(e) => setStart(e.target.value)}
                />
              </label>
              <label>
                结束
                <input
                  type="time"
                  max="22:00"
                  required
                  min={start}
                  value={end}
                  onChange={(e) => setEnd(e.target.value)}
                />
              </label>
            </div>
            {end <= start && (
              <p className="error">结束时间必须晚于开始时间。</p>
            )}
            <p className="range-summary">
              {start}–{end} · {validRange ? duration : 0} 分钟 · {names[state]}
            </p>
            {inspected && (
              <label>
                时段状态
                <select
                  value={state}
                  onChange={(e) => setState(e.target.value as Paint)}
                >
                  {(["free", "busy", "uncertain", "unknown"] as State[]).map(
                    (s) => (
                      <option key={s} value={s}>
                        {names[s]}
                      </option>
                    ),
                  )}
                  {scope === "activity" && (
                    <option value="inherit">恢复个人时间</option>
                  )}
                </select>
              </label>
            )}
            <button disabled={!validRange}>
              {editing !== null
                ? "更新待保存时段"
                : `加入待保存 · ${names[state]}`}
            </button>
            {inspected && (
              <div className="stack">
                <button
                  type="button"
                  disabled={!validRange}
                  onClick={() =>
                    add({ day, start, end, state: "unknown", weekly: false })
                  }
                >
                  清除此时段（设为未设置）
                </button>
                {scope === "activity" && (
                  <button
                    type="button"
                    disabled={!validRange}
                    onClick={() =>
                      add({ day, start, end, state: "inherit", weekly: false })
                    }
                  >
                    清除本次覆盖，恢复个人时间
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => {
                    setEditing(null);
                    setInspected("");
                    setState("free");
                  }}
                >
                  取消编辑
                </button>
              </div>
            )}
          </form>
          <article className="card stack">
            <h2>
              待保存 <span className="badge">{drafts.length}</span>
            </h2>
            <p className="muted">
              {scope === "activity"
                ? "仅影响本场约球，个人时间不会改变。"
                : "用于你参加的各场约球。"}
            </p>
            {drafts.map((d, i) => (
              <div className="draft-item" key={i}>
                <span className={`dot ${d.state}`} />
                <div>
                  <button
                    disabled={action.pending}
                    className="draft-edit"
                    onClick={() =>
                      inspect(
                        d.day,
                        Number(d.start.slice(0, 2)) * 2 +
                          Number(d.start.slice(3)) / 30,
                        i,
                      )
                    }
                  >
                    {d.day} {d.weekly ? "起每周重复" : ""} · 编辑
                  </button>
                  <small>
                    {d.start}–{d.end} · {names[d.state]}
                  </small>
                </div>
                <button
                  disabled={action.pending}
                  aria-label={`移除待保存时段 ${i + 1}`}
                  onClick={() => {
                    setDrafts((ds) => ds.filter((_, j) => j !== i));
                    setEditing(null);
                    setInspected("");
                  }}
                >
                  ×
                </button>
              </div>
            ))}
            {!drafts.length && (
              <p className="muted">先在时间表拖选一段时间。</p>
            )}
          </article>
        </aside>
      </div>
      <div className="time-savebar" aria-label="时间保存操作">
        <div>
          <strong>
            {drafts.length ? `待保存 ${drafts.length} 段` : "时间已同步"}
          </strong>
          <small>
            {scope === "activity" ? "仅本次活动" : "个人时间 · 用于所有活动"}
          </small>
        </div>
        <button
          disabled={!drafts.length || action.pending}
          onClick={() => {
            setDrafts((ds) => ds.slice(0, -1));
            setEditing(null);
            setInspected("");
          }}
        >
          撤销上一段
        </button>
        <button
          className="primary"
          disabled={!drafts.length || !loaded || action.pending}
          onClick={() =>
            void action.run(save, "时间已保存，活动推荐会使用最新时间。")
          }
        >
          {action.pending ? "正在保存…" : `保存 ${drafts.length} 段时间`}
        </button>
        {activityId && (
          <button
            disabled={!loaded || action.pending}
            onClick={async () => {
              if (
                !drafts.length ||
                (await action.run(save, "本次空闲时间已保存。"))
              )
                navigate(`/a/${activityId}`);
            }}
          >
            保存并返回活动
          </button>
        )}
      </div>
      <details className="card">
        <summary>已保存规则 · {data.rules.length} 条</summary>
        {data.rules.map((r: any) => (
          <div className="list-row" key={r.id}>
            <span className={`badge ${r.state}`}>
              {names[r.state as State]}
            </span>
            <div>
              {r.kind === "weekly"
                ? `每周 ${r.recurrence.weekdays.map((d: number) => weekdays[d % 7]).join("、")} · ${r.recurrence.start_time}–${r.recurrence.end_time}`
                : `${new Date(r.start_at).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai" })} — ${new Date(r.end_at).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai" })}`}
              <small>
                {r.source === "activity"
                  ? "本次活动"
                  : r.source === "course"
                    ? "导入课程"
                    : "个人时间"}
              </small>
            </div>
            {r.source !== "course" && (
              <button
                disabled={action.pending}
                onClick={() =>
                  action.run(async () => {
                    await api(
                      `/me/availability/rules/${r.id}?expected_revision=${data.revision}`,
                      { method: "DELETE" },
                    );
                    await load();
                  }, "规则已删除")
                }
              >
                删除
              </button>
            )}
          </div>
        ))}
      </details>
      <details className="card">
        <summary>从 WakeUp 导入课表</summary>
        <div className="stack">
          <p>课程导入为繁忙时段，确认前可查看预览。</p>
          <label>
            分享文字或口令
            <textarea
              value={share}
              onChange={(e) => {
                setShare(e.target.value);
                setPreview(null);
              }}
              rows={3}
            />
          </label>
          <button
            disabled={!share.trim() || action.pending}
            onClick={() =>
              action.run(async () => {
                setPreview(null);
                setPreview(
                  await api(
                    "/me/imports/wakeup/preview",
                    send({ share_text: share }),
                  ),
                );
              })
            }
          >
            {action.pending ? "正在处理…" : "预览课表"}
          </button>
          {preview && (
            <>
              <p>
                {preview.summary.course_count} 门课程 ·{" "}
                {preview.summary.occurrence_count} 个繁忙区间 ·{" "}
                {preview.term.start} 至 {preview.term.end}
              </p>
              <details>
                <summary>查看繁忙时段明细（北京时间，最多展示前 50 条）</summary>
                <ul>
                  {preview.busy_occurrences.slice(0, 50).map((item: { starts_at: string; ends_at: string; preview_title: string }, index: number) => (
                    <li key={index}>
                      {item.starts_at.slice(0, 10)} {item.starts_at.slice(11, 16)}–{item.ends_at.slice(11, 16)} · {item.preview_title}
                    </li>
                  ))}
                </ul>
              </details>
              <label>
                课表名称
                <input
                  value={label}
                  onChange={(e) => setLabel(e.target.value)}
                />
              </label>
              <button
                className="primary"
                disabled={action.pending}
                onClick={() =>
                  action.run(async () => {
                    await api(
                      "/me/imports/wakeup/confirm",
                      send({
                        preview_id: preview.preview_id,
                        label,
                        baseline_rules: [],
                        expected_revision: data.revision,
                      }),
                    );
                    setPreview(null);
                    setShare("");
                    await load();
                  }, "课表已导入")
                }
              >
                确认导入
              </button>
            </>
          )}
        </div>
      </details>
    </div>
  );
}
