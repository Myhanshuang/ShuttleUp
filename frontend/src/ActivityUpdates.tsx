import { useEffect, useState } from "react";
import { api } from "./api/client";
const labels: Record<string, string> = {
  "activity.created": "发起了活动",
  "activity.updated": "调整了活动安排",
  "availability.changed": "更新了空闲时间",
  "participant.joined": "加入了活动",
  "participant.updated": "更新了成员信息",
  "participant.removed": "移除了成员",
  "plan.selected": "选择了方案和名单",
  "rsvp.changed": "更新了参加回应",
  "booking.confirmed": "确认了场馆预约",
  "booking.recorded": "登记了订场",
  "booking.cancelled": "取消了订场",
  "attendance.changed": "更新了到场记录",
  "activity.finished": "结束了活动",
  "activity.cancelled": "取消了活动",
  "expense.created": "记录了一笔费用",
  "bill.published": "发布了账单",
  "payment.claimed": "声明已付款",
  "payment.confirmed": "确认了收款",
  "bill.settled": "完成了结算",
  "activity.archived": "归档了活动",
};
export default function ActivityUpdates({
  id,
  revision,
}: {
  id: string;
  revision?: number;
}) {
  const [items, setItems] = useState<any[]>([]),
    [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    const load = () =>
      api<any>(`/activities/${id}/events`)
        .then((r) => {
          if (active) {
            setItems(r.items);
            setError("");
          }
        })
        .catch(() => {
          if (active) setError("暂时无法读取动态，将自动重试。");
        });
    void load();
    const timer = window.setInterval(() => void load(), 20000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [id, revision]);
  return (
    <details className="card activity-updates">
      <summary>
        最近变更
        {items.length
          ? ` · ${items[0].actor_name}${labels[items[0].type] || "更新了活动"}`
          : ""}
      </summary>
      {error && <p className="muted">{error}</p>}
      {items.slice(0, 8).map((e) => (
        <div className="update-row" key={e.id}>
          <p>
            {e.actor_name}
            {labels[e.type] || "更新了活动"}
          </p>
          <time dateTime={e.occurred_at}>
            {new Date(e.occurred_at).toLocaleString("zh-CN", {
              timeZone: "Asia/Shanghai",
              month: "numeric",
              day: "numeric",
              hour: "2-digit",
              minute: "2-digit",
              hour12: false,
            })}
          </time>
        </div>
      ))}
      {!items.length && !error && <p className="muted">暂无变更。</p>}
    </details>
  );
}
