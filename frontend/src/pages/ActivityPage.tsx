import { useEffect, useRef, useState } from "react";
import { Link, useParams, useLocation } from "react-router-dom";
import { useSession } from "../session";
import ActivityProgress, { activityStep } from "../ActivityProgress";
import VenuePicker from "../VenuePicker";
import CandidateOptions from "../CandidateOptions";
import ActivityUpdates from "../ActivityUpdates";
import { api } from "../api/client";
import { money, shortDate, shortTime } from "../format";
import { addDays, Heading, send, statusLabel, useAction } from "../ui";
export default function ActivityPage() {
  const route = useLocation();
  const [editSettings, setEditSettings] = useState(false);
  const [changeNotice, setChangeNotice] = useState("");
  const [eventRevision, setEventRevision] = useState(0);
  const scheduleDirty = useRef(false);
  const [schedule, setSchedule] = useState<any>(null);
  const venueDirty = useRef(false);
  const [venueIds, setVenueIds] = useState<string[]>([]);
  const [diagnostics, setDiagnostics] = useState<any[]>([]);
  const { user } = useSession();
  const [memberAction, setMemberAction] = useState<any>(null);
  const { id } = useParams(),
    action = useAction(),
    [a, setA] = useState<any>(),
    [people, setPeople] = useState<any[]>([]),
    [candidates, setCandidates] = useState<any[]>([]),
    [otherWindows, setOtherWindows] = useState<any[]>([]),
    [bookings, setBookings] = useState<any[]>([]),
    [court, setCourt] = useState("1号场"),
    [order, setOrder] = useState(""),
    [reason, setReason] = useState(""),
    [cancel, setCancel] = useState(false),
    [bind, setBind] = useState(""),
    [invite, setInvite] = useState("");
  const [availability, setAvailability] = useState<Record<string, number>>({});
  async function load() {
    const activity = await api<any>(`/activities/${id}`);
    setA(activity);
    if (!scheduleDirty.current)
      setSchedule({
        date_from: activity.date_from,
        date_to: activity.date_to,
        duration_minutes: activity.duration_minutes,
        daily_windows: activity.daily_windows,
      });
    if (!venueDirty.current) setVenueIds(activity.venue_preferences || []);
    const [p, b] = await Promise.all([
      api<any>(`/activities/${id}/participants`),
      api<any>(`/activities/${id}/bookings`),
    ]);
    setPeople(p.items);
    setBookings(b.items);
    if (activity.status === "collecting") {
      const options = await api<any>(`/activities/${id}/candidates`);
      setCandidates(options.candidates);
      setOtherWindows(options.other_windows);
      setDiagnostics(options.diagnostics || []);
      const query = new URLSearchParams({
        from: `${activity.date_from}T00:00:00+08:00`,
        to: `${addDays(activity.date_to, 1)}T00:00:00+08:00`,
      });
      const shared = await api<any>(`/activities/${id}/availability?${query}`);
      const hours: Record<string, number> = {};
      for (const segment of shared.segments)
        for (const state of segment.states)
          if (state.state === "free")
            hours[state.participant_id] =
              (hours[state.participant_id] || 0) +
              (Date.parse(segment.ends_at) - Date.parse(segment.starts_at)) /
                3600000;
      setAvailability(hours);
    }
  }
  useEffect(() => {
    if (route.hash === "#activity-settings") setEditSettings(true);
  }, [route.hash]);
  useEffect(() => {
    void action.run(load);
    let timer: number;
    const events = new EventSource(`/api/v1/events?watch_activity_id=${id}`);
    events.addEventListener("resource.changed", (event) => {
      const change = JSON.parse((event as MessageEvent).data);
      setEventRevision((n) => n + 1);
      if (change.actor_user_id && change.actor_user_id !== user?.id)
        setChangeNotice(
          change.resource === "availability"
            ? "球友更新了空闲时间，方案已同步刷新。"
            : "活动有新变更，当前安排已同步更新。",
        );
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        void load().catch((e) =>
          action.run(async () => {
            throw e;
          }),
        );
      }, 200);
    });
    return () => {
      events.close();
      window.clearTimeout(timer);
    };
  }, [id]);
  async function mutate(path: string, body: unknown, method = "POST") {
    await api(`/activities/${id}/${path}`, send(body, method));
    await load();
    const notices: Record<string, string> = {
      rsvp: "参加回应已保存。",
      attendance: "到场记录已保存。",
      bookings: "订场已登记。",
      finish: "活动已结束，请核对到场和费用。",
      cancel: "活动已取消，请处理已发生的费用。",
    };
    action.report(notices[path] || "活动已更新。");
  }
  if (!a)
    return (
      <>
        {action.feedback}
        <p role="status">正在读取活动…</p>
      </>
    );
  const closed = ["finished", "cancelled"].includes(a.status),
    step = activityStep(a.status);
  const me = people.find((p) => p.id === a.my_participant_id),
    plan = a.current_plan;
  return (
    <>
      <Link className="back-link" to="/">
        ← 我的活动
      </Link>
      <Heading
        eyebrow={`活动短号 ${a.short_code} · ${a.is_host ? "我发起的" : "我参加的"}`}
        title={a.title}
      >
        {a.is_host && !closed && (
          <button
            onClick={() =>
              action.run(async () => {
                const data = await api<any>(`/activities/${id}/invite`);
                setInvite(`${location.origin}${data.url}`);
              })
            }
          >
            邀请球友
          </button>
        )}
      </Heading>
      <p className="muted">
        {plan
          ? `${shortDate(plan.starts_at)} ${shortTime(plan.starts_at)}–${shortTime(plan.ends_at)} · ${plan.snapshot?.venue_name || "已选场馆"}`
          : `${a.date_from} — ${a.date_to} · ${a.duration_minutes} 分钟`}{" "}
        · {a.participant_count} 人已加入
      </p>
      {action.feedback}
      {invite && (
        <div className="card stack">
          <label>
            邀请链接
            <input readOnly value={invite} onFocus={(e) => e.target.select()} />
          </label>
          <button
            onClick={() =>
              action.run(
                () => navigator.clipboard.writeText(invite),
                "邀请链接已复制",
              )
            }
          >
            复制邀请链接
          </button>
        </div>
      )}
      <ActivityProgress status={a.status} billingStatus={a.billing_status} />
      {changeNotice && (
        <div className="change-notice">
          <p>{changeNotice}</p>
          <button aria-label="关闭变更提示" onClick={() => setChangeNotice("")}>
            ×
          </button>
        </div>
      )}
      {a.status === "cancelled" && (
        <p className="notice">
          活动已取消：{a.cancel_reason || "请核对已有费用并处理结算。"}
        </p>
      )}
      <div className="detail-layout">
        <div className="stack">
          <article className="card next-step">
            <p className="eyebrow">现在要做的事</p>
            <h2>{a.next_action?.label || "查看本场安排"}</h2>
            <p>{a.next_action?.detail}</p>
            <div className="actions">
              {a.next_action?.href && a.next_action.href !== `/a/${id}` && (
                <Link className="button primary" to={a.next_action.href}>
                  {a.next_action.label}
                </Link>
              )}
              {step === 0 && a.next_action?.label !== "填写本次空闲时间" && (
                <Link className="button" to={`/me/time?activity_id=${id}`}>
                  调整我的空闲时间
                </Link>
              )}
            </div>
          </article>
          {step === 0 && (
            <CandidateOptions
              activity={a}
              people={people}
              candidates={candidates}
              diagnostics={diagnostics}
              otherWindows={otherWindows}
              reload={load}
            />
          )}
          {plan && (
            <article className="card stack" id="selected-plan">
              <p className="eyebrow">{statusLabel[a.status]}</p>
              <h2>
                {shortDate(plan.starts_at)} · {shortTime(plan.starts_at)}–
                {shortTime(plan.ends_at)}
              </h2>
              <p>
                {plan.snapshot?.venue_name || "所选场馆"} ·{" "}
                {plan.court_ids?.join("、")}
              </p>
              <p>
                本次名单：
                {people
                  .filter((p) => plan.roster_participant_ids?.includes(p.id))
                  .map((p) => p.display_name)
                  .join("、")}
              </p>
              {!closed && plan.roster_participant_ids?.includes(me?.id) && (
                <div>
                  <p>
                    你的回应：
                    {me?.rsvp === "yes"
                      ? "参加"
                      : me?.rsvp === "no"
                        ? "不参加"
                        : "待确认"}
                  </p>
                  <div className="actions">
                    <button
                      className={me?.rsvp === "yes" ? "primary" : ""}
                      disabled={action.pending}
                      onClick={() =>
                        action.run(() =>
                          mutate(
                            "rsvp",
                            { plan_id: a.current_plan_id, response: "yes" },
                            "PUT",
                          ),
                        )
                      }
                    >
                      确认参加
                    </button>
                    <button
                      disabled={action.pending}
                      onClick={() =>
                        action.run(() =>
                          mutate(
                            "rsvp",
                            { plan_id: a.current_plan_id, response: "no" },
                            "PUT",
                          ),
                        )
                      }
                    >
                      不参加
                    </button>
                  </div>
                </div>
              )}
              {bookings
                .filter((b) => b.status === "confirmed")
                .map((b) => (
                  <div className="list-row" key={b.id}>
                    <span>已登记 {b.court_ids.join("、")}</span>
                    <span>已付 {money(b.paid_total_cents)}</span>
                  </div>
                ))}
              {a.is_host &&
                a.status === "booking" &&
                !bookings.some((b) => b.status === "confirmed") && (
                  <button
                    disabled={action.pending}
                    onClick={() =>
                      void action.run(async () => {
                        await api(
                          `/activities/${id}/plan?expected_version=${a.version}`,
                          { method: "DELETE" },
                        );
                        await load();
                      })
                    }
                  >
                    清除方案，重新安排
                  </button>
                )}
              {a.is_host && a.status === "booking" && (
                <form
                  className="stack"
                  onSubmit={(e) => {
                    e.preventDefault();
                    void action.run(() =>
                      mutate("bookings", {
                        venue_id: plan.venue_id,
                        court_ids: court
                          .split(/[，,、]/)
                          .map((x) => x.trim())
                          .filter(Boolean),
                        starts_at: plan.starts_at,
                        ends_at: plan.ends_at,
                        external_order_no: order || null,
                        booker_participant_id: me.id,
                        expected_version: a.version,
                      }),
                    );
                  }}
                >
                  <h3>登记已经订好的场地</h3>
                  <label>
                    实际球场（多个用逗号分隔）
                    <input
                      required
                      value={court}
                      onChange={(e) => setCourt(e.target.value)}
                    />
                  </label>
                  <label>
                    订单号（可选）
                    <input
                      value={order}
                      onChange={(e) => setOrder(e.target.value)}
                    />
                  </label>
                  <button className="primary" disabled={action.pending}>
                    登记已订场
                  </button>
                  <small>实际支付金额在费用页记录。</small>
                </form>
              )}
              {a.status === "confirmed" && (
                <div className="actions">
                  <button
                    disabled={action.pending}
                    onClick={() =>
                      action.run(() =>
                        mutate(
                          "attendance",
                          {
                            entries: [
                              { participant_id: me.id, state: "present" },
                            ],
                            verify: false,
                          },
                          "PUT",
                        ),
                      )
                    }
                  >
                    我已到场
                  </button>
                  <button
                    disabled={action.pending}
                    onClick={() =>
                      action.run(() =>
                        mutate(
                          "attendance",
                          {
                            entries: [
                              { participant_id: me.id, state: "absent" },
                            ],
                            verify: false,
                          },
                          "PUT",
                        ),
                      )
                    }
                  >
                    我缺席
                  </button>
                  {a.is_host && (
                    <button
                      className="primary"
                      disabled={action.pending}
                      onClick={() =>
                        action.run(() =>
                          mutate("finish", { expected_version: a.version }),
                        )
                      }
                    >
                      结束活动，核对到场
                    </button>
                  )}
                </div>
              )}
            </article>
          )}
          <article className="card">
            <h2>
              {closed ? "核对实际到场" : "参与球友"}{" "}
              <span className="badge">
                {people.filter((p) => p.membership === "active").length}
              </span>
            </h2>
            {memberAction && (
              <div
                className="card stack"
                role="dialog"
                aria-label="确认成员变更"
              >
                <p>
                  {memberAction.membership === "active"
                    ? `将 ${memberAction.display_name} 移出本活动？移除后不能通过原邀请自行重新加入。`
                    : `恢复 ${memberAction.display_name} 的成员身份？`}
                </p>
                <div className="actions">
                  <button
                    disabled={action.pending}
                    onClick={() =>
                      void action.run(async () => {
                        await mutate(
                          `participants/${memberAction.id}`,
                          {
                            membership:
                              memberAction.membership === "active"
                                ? "removed"
                                : "active",
                            expected_version: a.version,
                          },
                          "PATCH",
                        );
                        setMemberAction(null);
                      })
                    }
                  >
                    确认{memberAction.membership === "active" ? "移除" : "恢复"}
                  </button>
                  <button
                    disabled={action.pending}
                    onClick={() => setMemberAction(null)}
                  >
                    取消
                  </button>
                </div>
              </div>
            )}
            {people.map((p) => (
              <div className="list-row" key={p.id}>
                <span className="avatar">{p.display_name.slice(0, 1)}</span>
                <div>
                  <strong>
                    {p.display_name}
                    {p.id === me?.id ? "（我）" : ""}
                  </strong>
                  <small>
                    {p.membership !== "active"
                      ? p.membership === "removed"
                        ? "已移除 · "
                        : "已退出 · "
                      : p.required
                        ? "核心成员 · "
                        : ""}
                    {plan &&
                    !closed &&
                    !plan.roster_participant_ids?.includes(p.id)
                      ? "未列入当前参加名单"
                      : step === 0
                        ? `已填写 ${(availability[p.id] || 0).toFixed(1)} 小时空闲`
                        : `${p.rsvp === "yes" ? "参加" : p.rsvp === "no" ? "不参加" : "待回应"} · ${p.attendance === "present" ? "到场" : p.attendance === "absent" ? "缺席" : "未登记"}${p.attendance_verified ? "（已核对）" : ""}`}
                  </small>
                </div>
                {!closed &&
                  (a.is_host || user?.is_admin) &&
                  p.user_id !== a.host_user_id &&
                  !(a.is_host && p.id === me?.id) && (
                    <button
                      disabled={action.pending}
                      onClick={() => setMemberAction(p)}
                    >
                      {p.membership === "removed"
                        ? "恢复成员"
                        : p.membership === "active"
                          ? "移除成员"
                          : "恢复成员"}
                    </button>
                  )}
                {closed && a.is_host && a.billing_status === "draft" && (
                  <div className="actions">
                    {["present", "absent"].map((s) => (
                      <button
                        key={s}
                        disabled={action.pending}
                        onClick={() =>
                          action.run(() =>
                            mutate(
                              "attendance",
                              {
                                entries: [{ participant_id: p.id, state: s }],
                                verify: true,
                              },
                              "PUT",
                            ),
                          )
                        }
                      >
                        {s === "present" ? "到场" : "缺席"}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </article>
        </div>
        <aside className="stack">
          <article className="card stack" id="activity-settings">
            <div className="section-head">
              <h2>本场信息</h2>
              {a.is_host && a.status === "collecting" && (
                <button
                  aria-expanded={editSettings}
                  onClick={() => setEditSettings(!editSettings)}
                >
                  {editSettings ? "收起编辑" : "调整活动安排"}
                </button>
              )}
            </div>
            <h3>活动安排 · 全体成员</h3>
            <p>
              {a.venue_summary?.map((v: any) => v.name).join("、") ||
                "尚未选择场馆"}
            </p>
            <p>
              {a.date_from}～{a.date_to} · 每次打球 {a.duration_minutes} 分钟
            </p>
            <p>
              {a.daily_windows
                .map((w: any) => `${w.start_time}～${w.end_time}`)
                .join("、")}{" "}
              内寻找方案
            </p>
            {a.is_host &&
              editSettings &&
              a.status === "collecting" &&
              schedule && (
                <form
                  className="stack"
                  aria-label="调整活动安排"
                  onSubmit={(e) => {
                    e.preventDefault();
                    void action.run(async () => {
                      await api(
                        `/activities/${id}`,
                        send(
                          { ...schedule, expected_version: a.version },
                          "PATCH",
                        ),
                      );
                      scheduleDirty.current = false;
                      await load();
                    }, "活动安排已保存，已重新计算方案。成员填写的空闲时间保持不变。");
                  }}
                >
                  <label>
                    活动打球时长（分钟）
                    <input
                      type="number"
                      required
                      min={30}
                      max={360}
                      step={15}
                      value={schedule.duration_minutes}
                      onChange={(e) => {
                        scheduleDirty.current = true;
                        setSchedule({
                          ...schedule,
                          duration_minutes: +e.target.value,
                        });
                      }}
                    />
                  </label>
                  <label>
                    活动开始日期
                    <input
                      type="date"
                      required
                      value={schedule.date_from}
                      onChange={(e) => {
                        scheduleDirty.current = true;
                        setSchedule({ ...schedule, date_from: e.target.value });
                      }}
                    />
                  </label>
                  <label>
                    活动截止日期
                    <input
                      type="date"
                      required
                      min={schedule.date_from}
                      max={
                        schedule.date_from
                          ? addDays(schedule.date_from, 13)
                          : undefined
                      }
                      value={schedule.date_to}
                      onChange={(e) => {
                        scheduleDirty.current = true;
                        setSchedule({ ...schedule, date_to: e.target.value });
                      }}
                    />
                  </label>
                  {schedule.daily_windows.map((w: any, i: number) => (
                    <div key={i} className="form-grid">
                      <label>
                        活动允许开始时间{i ? ` ${i + 1}` : ""}
                        <input
                          type="time"
                          required
                          value={w.start_time}
                          onChange={(e) => {
                            scheduleDirty.current = true;
                            setSchedule({
                              ...schedule,
                              daily_windows: schedule.daily_windows.map(
                                (x: any, j: number) =>
                                  j === i
                                    ? { ...x, start_time: e.target.value }
                                    : x,
                              ),
                            });
                          }}
                        />
                      </label>
                      <label>
                        活动允许结束时间{i ? ` ${i + 1}` : ""}
                        <input
                          type="time"
                          required
                          value={w.end_time}
                          onChange={(e) => {
                            scheduleDirty.current = true;
                            setSchedule({
                              ...schedule,
                              daily_windows: schedule.daily_windows.map(
                                (x: any, j: number) =>
                                  j === i
                                    ? { ...x, end_time: e.target.value }
                                    : x,
                              ),
                            });
                          }}
                        />
                      </label>
                    </div>
                  ))}
                  <small>
                    修改整场活动的时间要求，用于重新推荐方案；不会修改任何成员的空闲记录。
                  </small>
                  <button disabled={action.pending}>保存活动安排</button>
                </form>
              )}
            {a.is_host && !closed && a.status !== "collecting" && (
              <p>调整活动安排前，请先处理已有订场并清除当前方案。</p>
            )}
            {a.is_host && editSettings && a.status === "collecting" && (
              <form
                className="stack"
                onSubmit={(e) => {
                  e.preventDefault();
                  void action.run(async () => {
                    await api(
                      `/activities/${id}`,
                      send(
                        {
                          venue_preferences: venueIds,
                          expected_version: a.version,
                        },
                        "PATCH",
                      ),
                    );
                    venueDirty.current = false;
                    await load();
                  }, "活动场馆已保存，可重新检查方案。");
                }}
              >
                <VenuePicker
                  value={venueIds}
                  onChange={(ids) => {
                    venueDirty.current = true;
                    setVenueIds(ids);
                  }}
                />
                <button disabled={action.pending}>保存活动场馆</button>
              </form>
            )}
            <p>
              {a.min_players}–{a.max_players} 人 · {a.court_count} 块场地
            </p>
            <Link className="button" to={`/a/${id}/bill`}>
              本次活动费用与结算
            </Link>
            {!closed && (
              <section className="stack">
                <h3>我的本次空闲时间 · 仅本人</h3>
                <p>
                  填写我在这场活动中何时有空，不改变活动打球时长和日期要求。
                </p>
                <Link className="button" to={`/me/time?activity_id=${id}`}>
                  修改我的本次空闲时间
                </Link>
              </section>
            )}
          </article>
          <ActivityUpdates id={id!} revision={eventRevision} />
          {a.is_host && !closed && (
            <details className="card">
              <summary>群聊协作</summary>
              <p>可将这场网页活动关联到群，球友就能通过公共 Bot 参与。</p>
              <button
                disabled={action.pending}
                onClick={() =>
                  action.run(async () =>
                    setBind(
                      (
                        await api<any>(
                          `/activities/${id}/bot-bind-token`,
                          send({}),
                        )
                      ).code,
                    ),
                  )
                }
              >
                生成群关联码
              </button>
              {bind && (
                <p>
                  /羽球 关联 {bind}
                  <small>10 分钟内有效</small>
                </p>
              )}
            </details>
          )}
          {a.is_host && !closed && (
            <details className="card">
              <summary>活动管理</summary>
              <button className="danger" onClick={() => setCancel(!cancel)}>
                取消活动
              </button>
              {cancel && (
                <form
                  className="stack"
                  onSubmit={(e) => {
                    e.preventDefault();
                    void action.run(() =>
                      mutate("cancel", { reason, expected_version: a.version }),
                    );
                  }}
                >
                  <label>
                    取消原因
                    <input
                      required
                      value={reason}
                      onChange={(e) => setReason(e.target.value)}
                    />
                  </label>
                  <p>取消后仍需处理实际发生的费用。</p>
                  <button disabled={action.pending}>确认取消活动</button>
                </form>
              )}
            </details>
          )}
        </aside>
      </div>
    </>
  );
}
