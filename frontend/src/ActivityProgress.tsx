export function activityStep(status: string) {
  return status === "collecting"
    ? 0
    : status === "booking"
      ? 1
      : status === "confirmed"
        ? 2
        : 3;
}
export default function ActivityProgress({
  status,
  billingStatus = "draft",
}: {
  status: string;
  billingStatus?: string;
}) {
  const step = activityStep(status);
  if (status === "cancelled")
    return (
      <ol className="progress cancelled-progress" aria-label="本次活动流程">
        <li className="stopped">
          <span>×</span>活动已取消
        </li>
        <li
          className={billingStatus === "settled" ? "done" : "current"}
          aria-current={billingStatus === "settled" ? undefined : "step"}
        >
          <span>{billingStatus === "settled" ? "✓" : "·"}</span>
          {billingStatus === "settled" ? "已发生费用已结清" : "核对与结算"}
        </li>
      </ol>
    );
  const settled = status === "finished" && billingStatus === "settled";
  return (
    <ol className="progress" aria-label="本次活动流程">
      {[
        "收集时间",
        "订场确认",
        "到场打球",
        settled
          ? "全部结清"
          : billingStatus === "issued"
            ? "等待结清"
            : "核对与结算",
      ].map((label, i) => (
        <li
          key={label}
          className={settled || i < step ? "done" : i === step ? "current" : ""}
          aria-current={!settled && i === step ? "step" : undefined}
        >
          <span>{settled || i < step ? "✓" : `0${i + 1}`}</span>
          {label}
        </li>
      ))}
    </ol>
  );
}
