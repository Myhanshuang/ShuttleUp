import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useSession } from "../session";
import { Heading, send, useAction } from "../ui";
import { money } from "../format";
import ProviderLogin from "../ProviderLogin";

type Source = { id: string; label: string; enabled: boolean; manual: boolean };
type Venue = {
  id: string;
  provider_id: string;
  external_venue_id: string;
  name: string;
  address: string;
  timezone: string;
  booking_url: string;
  hourly_rate_cents: number | null;
  enabled: boolean;
  version: number;
};
type Draft = {
  name: string;
  address: string;
  booking_url: string;
  rate: string;
  provider_id: string;
  external_venue_id: string;
  timezone: string;
};

export default function AdminVenuesPage() {
  const { user } = useSession();
  if (!user?.is_admin)
    return (
      <article className="card empty">
        <h1>需要管理员权限</h1>
        <p>只有系统管理员可以维护场馆信息。</p>
        <Link to="/venues">查看可用场地</Link>
      </article>
    );
  return <VenueManager />;
}
function VenueManager() {
  const [items, setItems] = useState<Venue[] | null>(null),
    [sources, setSources] = useState<Source[]>([]);
  const [editing, setEditing] = useState<Venue | null>(null),
    [draft, setDraft] = useState<Draft | null>(null);
  const [confirm, setConfirm] = useState<Venue | null>(null),
    [loginSource, setLoginSource] = useState("");
  const action = useAction();
  async function reload() {
    const [venues, providers] = await Promise.all([
      api<{ items: Venue[] }>("/settings/venues"),
      api<{ items: Source[] }>("/settings/venue-sources"),
    ]);
    setItems(venues.items);
    setSources(providers.items);
  }
  useEffect(() => {
    void action.run(reload);
  }, []);
  function openEditor(venue?: Venue) {
    setEditing(venue || null);
    setDraft(
      venue
        ? {
            ...venue,
            rate:
              venue.hourly_rate_cents == null
                ? ""
                : (venue.hourly_rate_cents / 100).toFixed(2),
          }
        : {
            name: "",
            address: "",
            booking_url: "",
            rate: "",
            provider_id: sources.find((s) => s.enabled)?.id || "",
            external_venue_id: "",
            timezone: "Asia/Shanghai",
          },
    );
  }
  function field(key: keyof Draft, value: string) {
    setDraft((d) => (d ? { ...d, [key]: value } : null));
  }
  async function changeEnabled(venue: Venue) {
    await api(
      `/settings/venues/${venue.id}`,
      send(
        {
          name: venue.name,
          address: venue.address,
          booking_url: venue.booking_url,
          hourly_rate_cents: venue.hourly_rate_cents,
          enabled: !venue.enabled,
          expected_version: venue.version,
        },
        "PUT",
      ),
    );
    setConfirm(null);
    await reload();
  }
  return (
    <>
      <Heading eyebrow="维护公共场馆信息，供所有球友选择" title="场馆管理">
        <button
          className="primary"
          disabled={action.pending || !!draft}
          onClick={() => openEditor()}
        >
          添加场馆
        </button>
      </Heading>
      {action.feedback}
      <div className="section-head admin-venue-summary">
        <p className="muted">停用会隐藏场馆入口，历史活动和账单仍会保留。</p>
        <button
          disabled={action.pending}
          onClick={() => void action.run(reload)}
        >
          重新载入
        </button>
      </div>
      {draft && (
        <form
          className="card stack"
          aria-label={editing ? "编辑场馆" : "添加场馆"}
          onSubmit={(e) => {
            e.preventDefault();
            void action.run(
              async () => {
                const details = {
                  name: draft.name,
                  address: draft.address,
                  booking_url: draft.booking_url,
                  hourly_rate_cents:
                    draft.rate === ""
                      ? null
                      : Math.round(Number(draft.rate) * 100),
                };
                await api(
                  editing
                    ? `/settings/venues/${editing.id}`
                    : "/settings/venues",
                  send(
                    editing
                      ? {
                          ...details,
                          enabled: editing.enabled,
                          expected_version: editing.version,
                        }
                      : {
                          ...details,
                          provider_id: draft.provider_id,
                          external_venue_id: draft.external_venue_id,
                          timezone: draft.timezone,
                        },
                    editing ? "PUT" : "POST",
                  ),
                );
                setDraft(null);
                setEditing(null);
                await reload();
              },
              editing ? "场馆信息已更新" : "场馆已添加",
            );
          }}
        >
          <h2>{editing ? `编辑 ${editing.name}` : "添加新场馆"}</h2>
          <div className="form-grid">
            <label>
              场馆名称
              <input
                required
                maxLength={100}
                value={draft.name}
                onChange={(e) => field("name", e.target.value)}
              />
            </label>
            <label>
              参考价格（元 / 小时）
              <input
                type="number"
                min="0"
                max="1000000"
                step="0.01"
                placeholder="可留空"
                value={draft.rate}
                onChange={(e) => field("rate", e.target.value)}
              />
            </label>
          </div>
          <label>
            地址
            <input
              maxLength={240}
              value={draft.address}
              onChange={(e) => field("address", e.target.value)}
            />
          </label>
          <label>
            预约链接
            <input
              type="url"
              maxLength={2048}
              placeholder="https://"
              value={draft.booking_url}
              onChange={(e) => field("booking_url", e.target.value)}
            />
          </label>
          {editing ? (
            <p className="muted">
              场馆来源：
              {sources.find((s) => s.id === editing.provider_id)?.label}
              ；来源内编号：{editing.external_venue_id}；时区：
              {editing.timezone}
            </p>
          ) : (
            <>
              <div className="form-grid">
                <label>
                  场馆来源
                  <select
                    aria-label="场馆来源"
                    required
                    value={draft.provider_id}
                    onChange={(e) => field("provider_id", e.target.value)}
                  >
                    <option value="">请选择已接入的来源</option>
                    {sources
                      .filter((s) => s.enabled)
                      .map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.label}
                        </option>
                      ))}
                  </select>
                </label>
                <label>
                  来源内的场馆编号
                  <input
                    required
                    maxLength={100}
                    value={draft.external_venue_id}
                    onChange={(e) => field("external_venue_id", e.target.value)}
                  />
                </label>
              </div>
              <label>
                时区
                <input
                  required
                  maxLength={64}
                  value={draft.timezone}
                  onChange={(e) => field("timezone", e.target.value)}
                />
              </label>
              <p className="muted">
                使用该预约来源里的场馆编号来匹配余量。添加资料后仍需取得有效余量，才会生成可订方案。
              </p>
              {!sources.some((s) => s.enabled) && (
                <p className="notice">
                  暂无已启用的场馆来源，请先在服务器接入查询来源。
                </p>
              )}
            </>
          )}
          <div className="actions">
            <button
              className="primary"
              disabled={action.pending || (!editing && !draft.provider_id)}
            >
              保存场馆
            </button>
            <button
              type="button"
              disabled={action.pending}
              onClick={() => {
                setDraft(null);
                setEditing(null);
              }}
            >
              取消编辑
            </button>
          </div>
        </form>
      )}
      {confirm && (
        <section className="card stack" role="dialog" aria-label="确认停用场馆">
          <h2>停用「{confirm.name}」？</h2>
          <p>
            停用后，球友不能再选择该场馆，也不会为它推荐新方案。历史记录保留，之后可以重新启用。
          </p>
          <div className="actions">
            <button
              className="danger"
              disabled={action.pending}
              onClick={() =>
                void action.run(() => changeEnabled(confirm), "场馆已停用")
              }
            >
              确认停用
            </button>
            <button disabled={action.pending} onClick={() => setConfirm(null)}>
              取消
            </button>
          </div>
        </section>
      )}
      {!items ? (
        <p role="status">
          {action.error ? "场馆列表加载失败，请重新载入。" : "正在加载场馆…"}
        </p>
      ) : !items.length ? (
        <article className="card empty">
          <h2>还没有场馆</h2>
          <p>添加场馆后，球友就能在活动中选择它。</p>
        </article>
      ) : (
        <div className="activity-list">
          {items.map((venue) => (
            <article
              className="card stack"
              key={venue.id}
              aria-label={`场馆 ${venue.name}`}
            >
              <div className="section-head">
                <h2>{venue.name}</h2>
                <span
                  className={`badge ${venue.enabled ? "status-confirmed" : "status-cancelled"}`}
                >
                  {venue.enabled ? "已启用" : "已停用"}
                </span>
              </div>
              <p>{venue.address || "尚未填写地址"}</p>
              <p className="muted">
                {sources.find((s) => s.id === venue.provider_id)?.label ||
                  "场馆来源"}{" "}
                / 编号 {venue.external_venue_id}
                {venue.hourly_rate_cents != null
                  ? ` / 参考价 ${money(venue.hourly_rate_cents)} 每小时`
                  : ""}
              </p>
              <div className="actions">
                <button
                  disabled={action.pending || !!draft || !!confirm}
                  onClick={() => openEditor(venue)}
                >
                  编辑资料
                </button>
                <button
                  className={venue.enabled ? "danger" : ""}
                  disabled={action.pending || !!draft || !!confirm}
                  onClick={() =>
                    venue.enabled
                      ? setConfirm(venue)
                      : void action.run(
                          () => changeEnabled(venue),
                          "场馆已启用",
                        )
                  }
                >
                  {venue.enabled ? "停用场馆" : "启用场馆"}
                </button>
              </div>
            </article>
          ))}
        </div>
      )}
      <section className="card stack">
        <h2>场馆登录维护</h2>
        <p className="muted">同一来源下的场馆共用登录状态。</p>
        <label>
          维护的场馆来源
          <select
            value={loginSource}
            onChange={(e) => setLoginSource(e.target.value)}
          >
            <option value="">选择来源以查看登录状态</option>
            {sources
              .filter((s) => !s.manual)
              .map((s) => (
                <option key={s.id} value={s.id}>
                  {s.label}
                </option>
              ))}
          </select>
        </label>
        {loginSource && (
          <ProviderLogin
            key={loginSource}
            providerId={loginSource}
            onUpdated={() => void action.run(reload)}
          />
        )}
      </section>
    </>
  );
}
