import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
const Feedback = createContext<(message: string, error?: boolean) => void>(
  () => {},
);
export function FeedbackProvider({ children }: { children: ReactNode }) {
  const [message, setMessage] = useState<{
    text: string;
    error: boolean;
    id: number;
  } | null>(null);
  useEffect(() => {
    if (!message || message.error) return;
    const timer = window.setTimeout(() => setMessage(null), 8000);
    return () => window.clearTimeout(timer);
  }, [message]);
  return (
    <Feedback.Provider
      value={(text, error = false) =>
        setMessage({ text, error, id: Date.now() })
      }
    >
      {children}
      {message && (
        <div className={`feedback-toast ${message.error ? "error" : "notice"}`}>
          <p key={message.id} role={message.error ? "alert" : "status"}>
            {message.text}
          </p>
          <button aria-label="关闭提示" onClick={() => setMessage(null)}>
            ×
          </button>
        </div>
      )}
    </Feedback.Provider>
  );
}
export function useAction() {
  const report = useContext(Feedback);
  const count = useRef(0);
  const [error, setError] = useState(""),
    [pending, setPending] = useState(false),
    [notice, setNotice] = useState("");
  async function run(fn: () => Promise<unknown>, success = "") {
    count.current += 1;
    setPending(true);
    setError("");
    setNotice("");
    try {
      await fn();
      setNotice(success);
      if (success) report(success);
      return true;
    } catch (e) {
      const message = e instanceof Error ? e.message : "操作失败，请重试";
      setError(message);
      report(message, true);
      return false;
    } finally {
      count.current -= 1;
      setPending(count.current > 0);
    }
  }
  return {
    run,
    pending,
    notice,
    error,
    report,
    feedback: null,
  };
}
export function Heading({
  eyebrow,
  title,
  children,
}: {
  eyebrow: string;
  title: string;
  children?: ReactNode;
}) {
  return (
    <header className="page-head">
      <div>
        <h1>{title}</h1>
        <p className="page-description">{eyebrow}</p>
      </div>
      {children}
    </header>
  );
}
export const statusLabel: Record<string, string> = {
  collecting: "收集时间",
  booking: "订场确认",
  confirmed: "等待到场",
  finished: "活动结束",
  cancelled: "已取消",
  draft: "待出账",
  issued: "待结清",
  settled: "已结清",
};
export function localDay(date = new Date()) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}
export function addDays(day: string, count: number) {
  return localDay(
    new Date(new Date(`${day}T12:00:00+08:00`).getTime() + count * 86400000),
  );
}
export const send = (body: unknown, method = "POST"): RequestInit => ({
  method,
  headers: { "Idempotency-Key": crypto.randomUUID() },
  body: JSON.stringify(body),
});
