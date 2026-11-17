import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useSession } from "../session";
import { send, useAction } from "../ui";
export default function InvitePage() {
  const { token } = useParams(),
    session = useSession(),
    navigate = useNavigate(),
    action = useAction(),
    [summary, setSummary] = useState<any>(),
    [availability, setAvailability] = useState([{ date: "", start: "", end: "" }]);
  useEffect(() => {
    void action.run(async () => {
      const result = await api<any>(`/invites/${token}`);
      setSummary(result);
      setAvailability([{ date: result.date_from, start: "", end: "" }]);
    });
  }, [token]);
  const valid = availability.every((item) => item.date >= summary?.date_from && item.date <= summary?.date_to && item.start >= "08:00" && item.start < item.end && item.end <= "22:00");
  function update(index: number, key: "date" | "start" | "end", value: string) {
    setAvailability((items) => items.map((item, i) => i === index ? { ...item, [key]: value } : item));
  }
  return (
    <div className="card invite-card stack">
      {action.feedback}
      {summary && (
        <>
          <p className="eyebrow">{summary.host_name} 邀请你一起打球</p>
          <h1>{summary.title}</h1>
          <p>
            {summary.date_from} — {summary.date_to} ·{" "}
            {summary.participant_count} 人已加入
          </p>
          {session.user ? (
            <>
              <p>以 {session.user.display_name} 的身份加入</p>
              <button
                className="primary"
                disabled={action.pending || !valid || !["collecting", "booking", "confirmed"].includes(summary.status)}
                onClick={() =>
                  action.run(async () => {
                    const result = await api<any>(
                      `/invites/${token}/join`,
                      send({ availability }),
                    );
                    navigate(`/a/${result.activity.id}`);
                  })
                }
              >
                加入活动
              </button>
              <section className="stack" aria-label="加入前填写空闲时间">
                <h2>本次活动的空闲时间</h2>
                <p className="muted">请先填写至少一段空闲时间，再点击上方「加入活动」。仅用于本次活动，不修改个人时间或课表。</p>
                {availability.map((item, index) => (
                  <fieldset className="stack" key={index} disabled={action.pending}>
                    <legend>空闲时段 {index + 1}</legend>
                    <label>日期<input type="date" required min={summary.date_from} max={summary.date_to} value={item.date} onChange={(e) => update(index, "date", e.target.value)} /></label>
                    <div className="form-grid">
                      <label>开始时间<input type="time" required min="08:00" max="21:59" value={item.start} onChange={(e) => update(index, "start", e.target.value)} /></label>
                      <label>结束时间<input type="time" required min={item.start || "08:00"} max="22:00" value={item.end} onChange={(e) => update(index, "end", e.target.value)} /></label>
                    </div>
                    {item.start && item.end && (item.start < "08:00" || item.end > "22:00" || item.end <= item.start) && <p className="error">请填写 08:00–22:00 内有效的起止时间。</p>}
                    {availability.length > 1 && <button type="button" onClick={() => setAvailability((items) => items.filter((_, i) => i !== index))}>移除此时段</button>}
                  </fieldset>
                ))}
                <button type="button" disabled={action.pending || availability.length >= 28} onClick={() => setAvailability((items) => [...items, { date: summary.date_from, start: "", end: "" }])}>添加一段空闲时间</button>
              </section>
            </>
          ) : (
            <>
              <p>登录后加入，活动和时间表会保存在你的账号中。</p>
              <Link
                className="button primary"
                to={`/login?next=${encodeURIComponent(`/i/${token}`)}`}
              >
                登录 / 注册后加入
              </Link>
              <small>登录页也提供可选的游客入口。</small>
            </>
          )}
        </>
      )}
    </div>
  );
}
