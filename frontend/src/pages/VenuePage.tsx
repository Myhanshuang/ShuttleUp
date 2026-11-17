import { useEffect, useRef, useState } from "react";
import ProviderLogin from "../ProviderLogin";
import { useSession } from "../session";
import { api } from "../api/client";
import { money } from "../format";
import { addDays, Heading, localDay } from "../ui";

type Venue = { id: string; name: string; booking_url: string; provider_id: string };
type Slot = { external_slot_id: string; court_id: string; court_name: string; starts_at: string; ends_at: string; status: string; price_cents: number | null };
type Snapshot = { slots: Slot[]; fresh: boolean; fresh_until: string | null; last_success_at: string | null; last_error_code: string | null; next_poll_at: string; coverage: { booking_constraints?: Record<string, unknown> } };
const shortTime = (value: string) => new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(value));
const labels: Record<string, string> = { available: "可用", unavailable: "不可用", not_released: "未开放", unknown: "待核实" };
const sourceErrors: Record<string, string> = {
  AUTH_REQUIRED: "场馆查询尚未配置登录凭据，请联系管理员。",
  AUTH_EXPIRED: "场馆登录已失效，请管理员更新登录凭据。",
  AUTH_REJECTED: "场馆拒绝了查询身份，请管理员检查登录凭据。",
  SIGNATURE_REJECTED: "场馆查询协议有变，请联系管理员。",
  SOURCE_FORMAT_ERROR: "场馆返回的数据暂时无法识别。",
  SOURCE_RATE_LIMITED: "场馆查询繁忙，请稍后刷新。",
};
export default function VenuePage() {
  const { user } = useSession();
  const [venues, setVenues] = useState<Venue[]>([]), [venueId, setVenueId] = useState("");
  const [day, setDay] = useState(localDay()), [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState(""), [loading, setLoading] = useState(false), [now, setNow] = useState(Date.now());
  const sequence = useRef(0);
  useEffect(() => {
    let active = true;
    api<{ items: Venue[] }>("/venues").then(data => { if (active) { setVenues(data.items); setVenueId(data.items[0]?.id || ""); } }).catch(e => { if (active) setError(e.message); });
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => { active = false; sequence.current++; window.clearInterval(timer); };
  }, []);
  async function load(refresh = false) {
    const current = ++sequence.current;
    setLoading(true); setError(""); setSnapshot(null);
    try {
      const path = `/venues/${venueId}/${refresh ? "refresh" : "slots"}?date=${day}`;
      const result = refresh
        ? (await api<{ snapshot: Snapshot | null }>(path, { method: "POST" })).snapshot
        : await api<Snapshot>(path);
      if (current === sequence.current) { setSnapshot(result); if (!result) setError("查询正在冷却，请稍后刷新。"); }
    } catch (e) { if (current === sequence.current) setError(e instanceof Error ? e.message : "查询失败"); }
    finally { if (current === sequence.current) setLoading(false); }
  }
  useEffect(() => { if (venueId) void load(); return () => { sequence.current++; }; }, [venueId, day]);
  const fresh = !!snapshot?.fresh && !!snapshot.fresh_until && Date.parse(snapshot.fresh_until) >= now;
  const cooldown = snapshot ? Math.max(0, Math.ceil((Date.parse(snapshot.next_poll_at) - now) / 1000)) : 0;
  const courts = [...new Map((snapshot?.slots || []).map(slot => [slot.court_id, slot.court_name])).entries()];
  const intervals = [...new Map((snapshot?.slots || []).map(slot => [slot.starts_at, slot.ends_at])).entries()].sort(([a], [b]) => a.localeCompare(b));
  const cells = new Map((snapshot?.slots || []).map(slot => [`${slot.court_id}:${slot.starts_at}`, slot]));
  return <>
    <Heading eyebrow="先查看余量，再约好时间" title="可用场地" />
    <div className="card venue-controls">
      <label>场馆<select value={venueId} onChange={e => setVenueId(e.target.value)}>{venues.map(venue => <option key={venue.id} value={venue.id}>{venue.name}</option>)}</select></label>
      <label>日期<input type="date" min={localDay()} max={addDays(localDay(), 31)} value={day} onChange={e => { if (e.target.value) setDay(e.target.value); }} /></label>
      <button disabled={loading || !venueId || cooldown > 0} onClick={() => void load(true)}>{loading ? "查询中…" : cooldown ? `${cooldown} 秒后可刷新` : "刷新场地"}</button>
    </div>
    {user?.is_admin && venues.find(v => v.id === venueId)?.provider_id && <ProviderLogin key={venueId} providerId={venues.find(v => v.id === venueId)!.provider_id} onUpdated={() => void load()} />}
    {error && <p className="error" role="alert">{error}</p>}
    {!venues.length && !error && <p>暂无已配置的场馆。</p>}
    {snapshot?.last_error_code && <p className="error" role="alert">{sourceErrors[snapshot.last_error_code] || "场馆查询失败，请稍后刷新或联系管理员。"}</p>}
    {snapshot && <p role="status">{fresh ? "当前余量" : "数据未核实，不能作为可订依据"}{snapshot.last_success_at ? ` · 上次更新 ${new Date(snapshot.last_success_at).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai" })}` : ""}</p>}
    {!!courts.length && <div className="card venue-grid"><table><caption>各球场时段余量（北京时间）</caption><thead><tr><th scope="col">时段</th>{courts.map(([id, name]) => <th scope="col" key={id}>{name}</th>)}</tr></thead><tbody>{intervals.map(([start, end]) => <tr key={start}><th scope="row">{shortTime(start)}–{shortTime(end)}</th>{courts.map(([id]) => {
      const slot = cells.get(`${id}:${start}`), status = fresh && slot ? slot.status : "unknown";
      return <td key={id} className={`venue-cell ${status}`}><strong>{labels[status] || "待核实"}</strong>{slot?.price_cents != null && <small>{money(slot.price_cents)}</small>}</td>;
    })}</tr>)}</tbody></table></div>}
    <p className="muted">余量会随预约变化，实际预约时间和规则以场馆为准。此页面只查询，不会锁场或下单。</p>
  </>;
}
