import { useEffect, useRef, useState } from "react";
import { api } from "./api/client";

type LoginState = { supported: boolean; paused: boolean; last_verified_at: number | null; job: { id?: string; phase: string; message?: string } | null };
export default function ProviderLogin({ providerId, onUpdated }: { providerId: string; onUpdated: () => void }) {
  const [state, setState] = useState<LoginState | null>(null), [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const completed = useRef(""), callback = useRef(onUpdated);
  callback.current = onUpdated;
  const path = `/settings/providers/${providerId}/login`;
  useEffect(() => {
    let active = true;
    setState(null); setError(""); completed.current = "";
    async function poll() {
      try {
        const next = await api<LoginState>(path);
        if (!active) return;
        setState(next);
        if (next.job?.phase === "succeeded" && next.job.id !== completed.current) {
          completed.current = next.job.id || "";
          callback.current();
        }
      } catch (e) { if (active) setError(e instanceof Error ? e.message : "读取登录状态失败"); }
    }
    void poll();
    const timer = window.setInterval(poll, 2000);
    return () => { active = false; window.clearInterval(timer); };
  }, [path]);
  async function change(method: string) {
    setBusy(true); setError("");
    try { setState(await api<LoginState>(path, { method })); }
    catch (e) { setError(e instanceof Error ? e.message : "更新失败"); }
    finally { setBusy(false); }
  }
  if (!state?.supported && !error) return null;
  const active = ["starting", "waiting", "verifying"].includes(state?.job?.phase || "");
  return <section className="card" aria-label="场馆登录维护">
    <h2>场馆登录</h2>
    <p>{state?.paused ? "登录已失效，自动查询已暂停。" : "登录失效时会暂停查询，更新成功后自动恢复。"}</p>
    {state?.last_verified_at && <p>最近验证：{new Date(state.last_verified_at).toLocaleString("zh-CN")}</p>}
    {state?.job?.message && <p role="status">{state.job.message}</p>}
    {error && <p role="alert" className="error">{error}</p>}
    <button disabled={busy || active} onClick={() => void change("POST")}>{active ? "正在更新…" : "更新场馆登录"}</button>
    {active && <button disabled={busy} onClick={() => void change("DELETE")}>取消更新</button>}
    <p className="muted">更新会打开服务器本机终端。完成本机验证后，在微信中打开预约页面即可；无需复制令牌。</p>
  </section>;
}
