import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { shortTime } from "../format";
import { CourtIllustration } from "../visuals";
import VenuePicker from "../VenuePicker";
import { api } from "../api/client";
import { useSession } from "../session";
import {
  addDays,
  Heading,
  localDay,
  send,
  statusLabel,
  useAction,
} from "../ui";
export default function HomePage({ bills = false }: { bills?: boolean }) {
  const { user } = useSession(),
    navigate = useNavigate(),
    action = useAction();
  const [items, setItems] = useState<any[]>([]),
    [loading, setLoading] = useState(true),
    [create, setCreate] = useState(false),
    [history, setHistory] = useState(false);
  const [venueIds, setVenueIds] = useState<string[]>([]);
  const [title, setTitle] = useState("周末打球"),
    [from, setFrom] = useState(addDays(localDay(), 1)),
    [to, setTo] = useState(addDays(localDay(), 7)),
    [duration, setDuration] = useState(120),
    [min, setMin] = useState(4),
    [max, setMax] = useState(6);
  useEffect(() => {
    if (!user) {
      setLoading(false);
      return;
    }
    setLoading(true);
    void action.run(async () => {
      setItems(
        (await api<any>(`/activities?scope=${history ? "history" : "active"}`))
          .items,
      );
      setLoading(false);
    });
  }, [user?.id, history]);
  useEffect(() => {
    if (!user) return;
    const refresh = () => {
      if (document.visibilityState === "visible")
        void action.run(async () =>
          setItems(
            (
              await api<any>(
                `/activities?scope=${history ? "history" : "active"}`,
              )
            ).items,
          ),
        );
    };
    window.addEventListener("focus", refresh);
    return () => window.removeEventListener("focus", refresh);
  }, [user?.id, history]);
  const ordered = [...items].sort(
    (a, b) => Number(!!b.next_action?.needed) - Number(!!a.next_action?.needed),
  );
  const todoCount = ordered.filter((a) => a.next_action?.needed).length;
  return (
    <>
      <Heading
        eyebrow={
          bills ? "每次上场的费用，都在这里" : "约时间、找场地，安排下一次上场"
        }
        title={bills ? "费用与账单" : "一起约场球"}
      >
        {!bills && (
          <button
            className="primary"
            onClick={() => (user ? setCreate(!create) : navigate("/login"))}
          >
            ＋ 发起约球
          </button>
        )}
      </Heading>
      {!bills && !user && (
        <section className="court-banner">
          <div className="court-banner-copy">
            <h2>把时间约在一起。</h2>
            <p>
              邀请球友填好空闲时间，
              <br />
              找到合适的场地，就准备上场。
            </p>
            <div className="court-flow">
              <span>约时间</span>
              <i />
              <span>定场地</span>
              <i />
              <span>一起打球</span>
            </div>
          </div>
          <CourtIllustration />
        </section>
      )}
      {action.feedback}
      {create && (
        <form
          className="card stack"
          onSubmit={(e) => {
            e.preventDefault();
            void action.run(async () => {
              const a = await api<any>(
                "/activities",
                send({
                  title,
                  venue_preferences: venueIds,
                  date_from: from,
                  date_to: to,
                  duration_minutes: duration,
                  min_players: min,
                  max_players: max,
                }),
              );
              navigate(`/a/${a.id}`);
            });
          }}
        >
          <h2>发起一场约球</h2>
          <label>
            活动标题
            <input
              required
              maxLength={80}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </label>
          <div className="form-grid">
            <label>
              开始日期
              <input
                type="date"
                required
                value={from}
                onChange={(e) => setFrom(e.target.value)}
              />
            </label>
            <label>
              截止日期
              <input
                type="date"
                required
                min={from}
                max={addDays(from, 13)}
                value={to}
                onChange={(e) => setTo(e.target.value)}
              />
            </label>
            <label>
              打球时长（分钟）
              <input
                type="number"
                min={30}
                max={360}
                step={15}
                value={duration}
                onChange={(e) => setDuration(+e.target.value)}
              />
            </label>
            <label>
              最少人数
              <input
                type="number"
                min={2}
                max={30}
                value={min}
                onChange={(e) => setMin(+e.target.value)}
              />
            </label>
            <label>
              最多人数
              <input
                type="number"
                min={min}
                max={30}
                value={max}
                onChange={(e) => setMax(+e.target.value)}
              />
            </label>
          </div>
          <VenuePicker value={venueIds} onChange={setVenueIds} />
          <p className="muted">
            在所选日期的 18:00–22:00 内寻找合适时段，默认需要 1 块场地。
          </p>
          <div className="actions">
            <button className="primary" disabled={action.pending}>
              创建活动并邀请球友
            </button>
            <button type="button" onClick={() => setCreate(false)}>
              收起
            </button>
          </div>
        </form>
      )}
      <div className="section-head">
        <h2>{bills ? "按活动查看账单" : "我的活动"}</h2>
        {user && (
          <div className="segmented">
            <button
              className={!history ? "selected" : ""}
              onClick={() => setHistory(false)}
            >
              当前活动
            </button>
            <button
              className={history ? "selected" : ""}
              onClick={() => setHistory(true)}
            >
              已归档
            </button>
          </div>
        )}
      </div>
      {!user ? (
        <article className="card empty">
          <h2>登录后，接着安排你的下一场球</h2>
          <p>在这里查看发起和参加的活动，以及每场的下一步。</p>
          <Link className="button primary" to="/login">
            登录 / 注册
          </Link>
        </article>
      ) : loading && !action.error ? (
        <p role="status">正在读取活动…</p>
      ) : items.length ? (
        <div className="activity-list">
          {ordered.map((a, index) => {
            const day = a.current_plan
              ? localDay(new Date(a.current_plan.starts_at))
              : a.date_from;
            return (
              <div key={a.id}>
                {!history &&
                  !bills &&
                  (index === 0 || (index === todoCount && todoCount > 0)) && (
                    <h3 className="activity-group-label">
                      {a.next_action?.needed
                        ? `需要我处理 · ${todoCount}`
                        : "其他活动"}
                    </h3>
                  )}
                <Link
                  className="card activity-card"
                  to={
                    bills
                      ? `/a/${a.id}/bill`
                      : a.next_action?.href || `/a/${a.id}`
                  }
                >
                  <div className="activity-date" aria-hidden="true">
                    <span>{Number(day.slice(5, 7))} 月</span>
                    <strong>{day.slice(8, 10)}</strong>
                  </div>
                  <div className="activity-info">
                    <div className="activity-meta">
                      <span
                        className={`badge status-${bills ? a.billing_status : a.status}`}
                      >
                        {statusLabel[bills ? a.billing_status : a.status]}
                      </span>
                      <span>{a.is_host ? "我发起的" : "我参加的"}</span>
                    </div>
                    <h2>{a.title}</h2>
                    <p>
                      {a.current_plan ? (
                        <>
                          {day} {shortTime(a.current_plan.starts_at)}–
                          {shortTime(a.current_plan.ends_at)}
                          <br />
                          {a.current_plan.snapshot?.venue_name || "已选场馆"}
                        </>
                      ) : (
                        <>
                          待定日期：{a.date_from} 至 {a.date_to}
                        </>
                      )}
                      <span className="activity-people">
                        {a.participant_count} 人已加入
                      </span>
                    </p>
                  </div>
                  <strong className="activity-next">
                    {bills ? "查看费用" : a.next_action?.label || "查看活动"}
                    <span aria-hidden="true">›</span>
                  </strong>
                </Link>
              </div>
            );
          })}
        </div>
      ) : (
        <article className="card empty">
          <h2>{history ? "还没有归档活动" : "下一场，从你发起"}</h2>
          <p>发起约球或通过球友的邀请链接加入，活动就会显示在这里。</p>
        </article>
      )}
    </>
  );
}
