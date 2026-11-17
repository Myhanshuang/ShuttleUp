import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "./api/client";
import { money, shortDate, shortTime } from "./format";
import { send, useAction } from "./ui";

export default function CandidateOptions({
  activity: a,
  people,
  candidates,
  diagnostics,
  otherWindows,
  reload,
}: any) {
  const action = useAction();
  const [preview, setPreview] = useState<any>(null),
    [minutes, setMinutes] = useState(
      Math.max(30, Math.floor(a.duration_minutes / 30) * 15),
    );
  const [choice, setChoice] = useState<any>(null),
    [roster, setRoster] = useState<string[]>([]),
    [comparing, setComparing] = useState(false);
  useEffect(() => {
    setChoice(null);
    setPreview(null);
  }, [a.version]);
  const names = (ids: string[] = []) =>
    ids
      .map(
        (id) =>
          people.find((p: any) => p.id === id)?.display_name || "已离开成员",
      )
      .join("、") || "无";
  const range = (c: any) =>
    `${shortDate(c.starts_at)} ${shortTime(c.starts_at)}–${shortTime(c.ends_at)}`;
  function facts(c: any) {
    return (
      <div className="candidate-facts">
        <p>
          {c.venue_name} · {c.court_ids.length} 块场地 ·{" "}
          {c.continuous_court_count} 块连续可用
        </p>
        <p>
          <strong>全程有空：</strong>
          {names(c.eligible_participant_ids)}
        </p>
        {!!c.busy_participant_ids?.length && (
          <p>
            <strong>有冲突：</strong>
            {names(c.busy_participant_ids)}
          </p>
        )}
        {!!c.uncertain_participant_ids?.length && (
          <p>
            <strong>不确定：</strong>
            {names(c.uncertain_participant_ids)}
          </p>
        )}
        {!!c.unknown_participant_ids?.length && (
          <p>
            <strong>尚未确认空闲：</strong>
            {names(c.unknown_participant_ids)}
          </p>
        )}
        <p>
          场地费合计 <strong>{money(c.total_price_cents)}</strong>
          <small>仅含所选场地整个时段；球费另计，实际费用以订单为准。</small>
        </p>
        {c.last_success_at && (
          <small>
            余量更新于 {shortTime(c.last_success_at)}；选择时会再次核验。
          </small>
        )}
      </div>
    );
  }
  return (
    <article className="card stack" id="candidates">
      <div className="section-head">
        <h2>
          可选方案 <span className="badge">{candidates.length}</span>
        </h2>
        <button
          disabled={action.pending}
          onClick={() =>
            void action.run(async () => {
              await api(`/activities/${a.id}/candidates/refresh`, {
                method: "POST",
              });
              await reload();
            }, "已检查最新场地与人员。")
          }
        >
          {action.pending ? "正在检查…" : "重新检查方案"}
        </button>
      </div>
      <p className="muted">
        当前要求 {a.duration_minutes} 分钟、{a.min_players}–{a.max_players} 人、
        {a.court_count} 块连续场地。所有核心成员需全程有空。
      </p>
      {diagnostics.length > 0 && (
        <details open={!candidates.length}>
          <summary>方案检查结果</summary>
          <ul>
            {diagnostics.map((d: any, i: number) => (
              <li key={i}>
                {d.message}
                {d.count ? `（${d.count} 个时段）` : ""}
              </li>
            ))}
          </ul>
        </details>
      )}
      {!a.venue_preferences.length && a.is_host && (
        <Link className="button" to={`/a/${a.id}#activity-settings`}>
          选择活动场馆
        </Link>
      )}
      {candidates.length ? (
        candidates.map((c: any) => (
          <section className="candidate-option" key={c.id}>
            <h3>{range(c)}</h3>
            {facts(c)}
            {a.is_host && (
              <button
                className="primary"
                disabled={action.pending}
                onClick={() => {
                  setChoice(c);
                  setRoster(
                    people
                      .filter((p: any) =>
                        c.eligible_participant_ids.includes(p.id),
                      )
                      .sort(
                        (x: any, y: any) =>
                          Number(y.required) - Number(x.required),
                      )
                      .slice(0, a.max_players)
                      .map((p: any) => p.id),
                  );
                }}
              >
                选择方案
              </button>
            )}
            {choice?.id === c.id && (
              <form
                className="roster-review stack"
                aria-label="确认方案与参加名单"
                onSubmit={(e) => {
                  e.preventDefault();
                  void action.run(async () => {
                    await api(
                      `/activities/${a.id}/plans`,
                      send({
                        candidate_id: c.id,
                        roster_participant_ids: roster,
                        expected_version: a.version,
                      }),
                    );
                    setChoice(null);
                    await reload();
                  }, "方案和名单已确定，请继续完成场馆预约。");
                }}
              >
                <h3>确认本次参加名单</h3>
                <p>
                  已选 {roster.length} 人，需 {a.min_players}–{a.max_players}{" "}
                  人。核心成员必须参加；其他有空成员可勾选。
                </p>
                {people
                  .filter((p: any) => c.eligible_participant_ids.includes(p.id))
                  .map((p: any) => (
                    <label className="check" key={p.id}>
                      <input
                        type="checkbox"
                        checked={roster.includes(p.id)}
                        disabled={p.required || action.pending}
                        onChange={(e) =>
                          setRoster((ids) =>
                            e.target.checked
                              ? [...ids, p.id]
                              : ids.filter((id) => id !== p.id),
                          )
                        }
                      />
                      {p.display_name}
                      {p.required ? "（核心成员）" : ""}
                    </label>
                  ))}
                <p className="muted">
                  确认后进入订场确认，名单中的成员需要回应是否参加；此操作不会预约场地。
                </p>
                <div className="actions">
                  <button
                    className="primary"
                    disabled={
                      action.pending ||
                      roster.length < a.min_players ||
                      roster.length > a.max_players
                    }
                  >
                    确认名单并进入订场
                  </button>
                  <button type="button" onClick={() => setChoice(null)}>
                    暂不选择
                  </button>
                </div>
              </form>
            )}
          </section>
        ))
      ) : (
        <p className="empty">
          还没有满足条件的方案。可以先补齐时间和场馆，或预览缩短时长后的结果。
        </p>
      )}
      {!!otherWindows.length && (
        <details>
          <summary>查看接近条件的时段</summary>
          {otherWindows.slice(0, 5).map((c: any) => (
            <div className="candidate-option" key={c.id}>
              <strong>
                {range(c)} · {c.venue_name}
              </strong>
              <p>
                全程有空 {c.eligible_participant_ids.length} 人，要求至少{" "}
                {a.min_players} 人；连续场地 {c.continuous_court_count} 块，要求{" "}
                {a.court_count} 块。
              </p>
              {!!c.missing_required_participant_ids.length && (
                <p>
                  核心成员尚未确认空闲：
                  {names(c.missing_required_participant_ids)}
                </p>
              )}
              {c.classification === "needs_court_check" && (
                <p>场地数据缺少具体球场信息，需要进一步核实。</p>
              )}
              <small>当前不满足条件，不能直接选择。</small>
            </div>
          ))}
        </details>
      )}
      <button
        aria-expanded={comparing}
        onClick={() => setComparing(!comparing)}
      >
        预览调整打球时长
      </button>
      {comparing && (
        <section className="adjustment-preview stack">
          <h3>先看看调整后的结果</h3>
          <p className="muted">
            仅调整预览时长，人数、核心成员、场馆和日期要求保持一致。活动尚未修改。
          </p>
          <div className="actions">
            <label>
              预览打球时长
              <select
                value={minutes}
                disabled={action.pending}
                onChange={(e) => {
                  setMinutes(+e.target.value);
                  setPreview(null);
                }}
              >
                {Array.from({ length: 23 }, (_, i) => 30 + i * 15).map((m) => (
                  <option key={m} value={m}>
                    {m} 分钟{m === a.duration_minutes ? "（当前）" : ""}
                  </option>
                ))}
              </select>
            </label>
            <button
              disabled={action.pending}
              onClick={() =>
                void action.run(async () =>
                  setPreview(
                    await api(
                      `/activities/${a.id}/candidates/preview?duration_minutes=${minutes}`,
                    ),
                  ),
                )
              }
            >
              预览方案
            </button>
          </div>
          {preview && (
            <>
              <p>
                <strong>
                  {preview.original_duration_minutes} →{" "}
                  {preview.duration_minutes} 分钟
                </strong>
                ：找到 {preview.candidates.length} 个满足条件的方案
                {preview.candidates.length === 20 ? "（最多展示 20 个）" : ""}。
              </p>
              {preview.candidates.slice(0, 3).map((c: any) => (
                <div className="candidate-option" key={c.id}>
                  <h3>{range(c)}</h3>
                  {facts(c)}
                </div>
              ))}
              {!preview.candidates.length && (
                <p>缩短或调整时长后仍无可用方案，请检查人员时间和场地余量。</p>
              )}
              {a.is_host && preview.duration_minutes !== a.duration_minutes && (
                <button
                  className="primary"
                  disabled={action.pending}
                  onClick={() =>
                    void action.run(async () => {
                      await api(
                        `/activities/${a.id}`,
                        send(
                          {
                            duration_minutes: preview.duration_minutes,
                            expected_version: preview.activity_version,
                          },
                          "PATCH",
                        ),
                      );
                      setPreview(null);
                      setComparing(false);
                      await reload();
                    }, "活动时长已调整，方案已重新生成；请选择方案并核对名单。")
                  }
                >
                  采用 {preview.duration_minutes} 分钟，重新生成方案
                </button>
              )}
              {!a.is_host && (
                <p className="muted">
                  仅主持人可以采用调整。可将这个时长建议告诉主持人。
                </p>
              )}
            </>
          )}
        </section>
      )}
    </article>
  );
}
