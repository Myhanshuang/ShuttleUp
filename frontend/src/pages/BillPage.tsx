import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import ActivityProgress from "../ActivityProgress";
import ActivityUpdates from "../ActivityUpdates";
import { api, ApiError } from "../api/client";
import { money } from "../format";
import { Heading, send, statusLabel, useAction } from "../ui";
export default function BillPage() {
  const { id } = useParams();
  return id ? (
    <ActivityBill key={id} id={id} />
  ) : (
    <p role="alert">缺少活动信息。</p>
  );
}
function ActivityBill({ id }: { id: string }) {
  const action = useAction(),
    [a, setA] = useState<any>(),
    [people, setPeople] = useState<any[]>([]),
    [expenses, setExpenses] = useState<any[]>([]),
    [bill, setBill] = useState<any>(null),
    [preview, setPreview] = useState<any>(null),
    [previewError, setPreviewError] = useState("");
  const [amount, setAmount] = useState(""),
    [description, setDescription] = useState("球钱"),
    [kind, setKind] = useState("shuttle"),
    [payer, setPayer] = useState("");
  async function load() {
    const activity = await api<any>(`/activities/${id}`);
    setA(activity);
    const [p, e] = await Promise.all([
      api<any>(`/activities/${id}/participants`),
      api<any>(`/activities/${id}/expenses`),
    ]);
    setPeople(p.items);
    setExpenses(e.items);
    setPayer((v) => v || activity.my_participant_id);
    if (activity.billing_status !== "draft") {
      setBill(await api(`/activities/${id}/bill`));
    } else {
      setBill(null);
      if (["finished", "cancelled"].includes(activity.status)) {
        try {
          setPreview(await api(`/activities/${id}/bill/preview`));
          setPreviewError("");
        } catch (e) {
          if (e instanceof ApiError && [409, 422].includes(e.status)) {
            setPreview(null);
            setPreviewError(e.message);
          } else throw e;
        }
      }
    }
  }
  useEffect(() => {
    void action.run(load);
    const events = new EventSource(`/api/v1/events?watch_activity_id=${id}`);
    let timer: number;
    events.addEventListener("resource.changed", () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => void action.run(load), 250);
    });
    return () => {
      events.close();
      window.clearTimeout(timer);
    };
  }, [id]);
  async function mutate(path: string, body: unknown = {}) {
    await api(`/activities/${id}/${path}`, send(body));
    await load();
    action.report(
      path.includes("confirm")
        ? "已确认收款。"
        : path === "payments"
          ? "已声明付款，等待对方确认。"
          : path === "bill/publish"
            ? "账单已发布。"
            : "本次费用已更新。",
    );
  }
  const closed = a && ["finished", "cancelled"].includes(a.status);
  return (
    <>
      <Link className="back-link" to={`/a/${id}`}>
        ← 返回本次活动
      </Link>
      <Heading eyebrow="本次活动结算" title={a?.title || "正在读取本次活动…"}>
        {a && <span className="badge">{statusLabel[a.billing_status]}</span>}
      </Heading>
      {a && (
        <p className="muted">
          活动 {a.short_code} · {a.date_from}～{a.date_to} ·
          本页仅显示这次活动的费用、分摊和收付款。
        </p>
      )}
      {a && (
        <ActivityProgress status={a.status} billingStatus={a.billing_status} />
      )}
      {a && !closed && (
        <p className="notice">
          活动仍处于「{statusLabel[a.status]}
          」阶段，这里可先记录本次费用；结束活动并核对到场后再结算。
        </p>
      )}
      {a?.status === "cancelled" && (
        <p className="notice">
          本次活动已取消，仍需核对已发生的费用并完成结算。
        </p>
      )}
      {action.feedback}
      <ActivityUpdates id={id} revision={a?.version} />
      <div className="detail-layout">
        <div className="stack">
          {bill && (
            <article className="card next-step">
              <p className="eyebrow">本场我的应收应付</p>
              <h2>
                {bill.my_summary.balance_cents < 0
                  ? `还需支付 ${money(-bill.my_summary.balance_cents)}`
                  : bill.my_summary.balance_cents > 0
                    ? `还应收 ${money(bill.my_summary.balance_cents)}`
                    : "你的账已结清"}
              </h2>
              <p>实际转账后声明付款，由收款人确认。</p>
              {bill.my_summary.outgoing.map((t: any) => (
                <div className="list-row" key={t.id}>
                  <span>
                    向{" "}
                    {
                      bill.snapshot.participant_snapshots.find(
                        (p: any) => p.id === t.to_participant_id,
                      )?.name
                    }{" "}
                    支付 {money(t.remaining_cents)}
                  </span>
                  <button
                    disabled={action.pending || t.pending_cents > 0}
                    onClick={() =>
                      action.run(() =>
                        mutate("payments", {
                          bill_revision_id: bill.id,
                          transfer_id: t.id,
                          amount_cents: t.remaining_cents,
                        }),
                      )
                    }
                  >
                    {t.pending_cents ? "等待对方确认" : "我已付款"}
                  </button>
                </div>
              ))}
              {bill.payment_claims
                .filter(
                  (p: any) =>
                    p.status === "claimed" &&
                    bill.my_summary.incoming.some(
                      (t: any) => t.id === p.transfer_id,
                    ),
                )
                .map((p: any) => (
                  <div className="list-row" key={p.id}>
                    <span>
                      待确认收款 {money(p.amount_cents)} · {p.short_code}
                    </span>
                    <button
                      disabled={action.pending}
                      onClick={() =>
                        action.run(() => mutate(`payments/${p.id}/confirm`))
                      }
                    >
                      确认收款
                    </button>
                  </div>
                ))}
            </article>
          )}
          <article className="card">
            <div className="section-head">
              <h2>本次活动支出</h2>
              <strong className="total">
                {money(expenses.reduce((sum, e) => sum + e.amount_cents, 0))}
              </strong>
            </div>
            {expenses.length ? (
              expenses.map((e) => (
                <div className="list-row" key={e.id}>
                  <div>
                    <strong>{e.description}</strong>
                    <small>
                      {
                        people.find((p) => p.id === e.payer_participant_id)
                          ?.display_name
                      }{" "}
                      垫付 · {e.short_code}
                    </small>
                  </div>
                  <strong>{money(e.amount_cents)}</strong>
                </div>
              ))
            ) : (
              <p className="empty">这次活动还没有记录支出。</p>
            )}
          </article>
          {a?.billing_status === "draft" && (
            <article className="card stack">
              <h2>{closed ? "出账前核对" : "活动进行中，先记费用"}</h2>
              <p>
                {closed
                  ? "核对实际到场成员后，按已记录费用生成 AA 账单。"
                  : "结束活动并核对到场后，才能发布账单。"}
              </p>
              {previewError && <p className="notice">{previewError}</p>}
              {closed && <Link to={`/a/${id}`}>去核对到场 →</Link>}
              {preview && (
                <>
                  <p>
                    合计 {money(preview.total_cents)} ·{" "}
                    {preview.transfers.length} 笔转账
                  </p>
                  {preview.transfers.map((t: any) => (
                    <p key={t.id}>
                      {
                        people.find((p) => p.id === t.from_participant_id)
                          ?.display_name
                      }{" "}
                      →{" "}
                      {
                        people.find((p) => p.id === t.to_participant_id)
                          ?.display_name
                      }{" "}
                      · {money(t.amount_cents)}
                    </p>
                  ))}
                  {a.is_host && (
                    <button
                      className="primary"
                      disabled={action.pending}
                      onClick={() =>
                        action.run(() =>
                          mutate("bill/publish", {
                            expected_generation: a.bill_generation,
                          }),
                        )
                      }
                    >
                      确认并发布账单
                    </button>
                  )}
                </>
              )}
            </article>
          )}
        </div>
        {a?.billing_status === "draft" && (
          <form
            className="card stack"
            onSubmit={(e) => {
              e.preventDefault();
              void action.run(async () => {
                if (!/^\d+(\.\d{1,2})?$/.test(amount))
                  throw new Error("金额最多保留两位小数");
                const [yuan, fen = ""] = amount.split(".");
                await mutate("expenses", {
                  kind,
                  description,
                  amount_cents: Number(yuan) * 100 + Number(fen.padEnd(2, "0")),
                  payer_participant_id: payer,
                  split_mode: "equal",
                  split_scope: "attendees",
                  shares: [],
                });
                setAmount("");
              }, "费用已记录");
            }}
          >
            <h2>为本次活动记一笔费用</h2>
            <label>
              类型
              <select value={kind} onChange={(e) => setKind(e.target.value)}>
                <option value="shuttle">球钱</option>
                <option value="venue">场地费</option>
                <option value="extra">其他 AA</option>
              </select>
            </label>
            <label>
              说明
              <input
                required
                maxLength={120}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </label>
            <label>
              金额（元）
              <input
                required
                inputMode="decimal"
                value={amount}
                placeholder="0.00"
                onChange={(e) => setAmount(e.target.value)}
              />
            </label>
            <label>
              垫付人
              <select value={payer} onChange={(e) => setPayer(e.target.value)}>
                {people.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.display_name}
                  </option>
                ))}
              </select>
            </label>
            <p className="muted">按主持人核对的实际到场成员平均分摊。</p>
            <button className="primary" disabled={action.pending}>
              记录实际支出
            </button>
          </form>
        )}
      </div>
    </>
  );
}
