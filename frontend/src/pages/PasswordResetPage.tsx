import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import { useSession } from "../session";
import { useAction } from "../ui";

export default function PasswordResetPage() {
  const [params] = useSearchParams();
  const loginUrl = `/login?next=${encodeURIComponent(params.get("next") || "/")}`;
  const action = useAction(),
    mail = useAction(),
    session = useSession();
  const [email, setEmail] = useState(""),
    [code, setCode] = useState(""),
    [password, setPassword] = useState(""),
    [confirm, setConfirm] = useState("");
  const [challenge, setChallenge] = useState(""),
    [cooldown, setCooldown] = useState(0),
    [ready, setReady] = useState(false),
    [done, setDone] = useState(false);
  useEffect(() => {
    void action.run(async () =>
      setReady((await api<any>("/auth/options")).email_registration),
    );
  }, []);
  useEffect(() => {
    if (!cooldown) return;
    const timer = window.setTimeout(() => setCooldown(cooldown - 1), 1000);
    return () => window.clearTimeout(timer);
  }, [cooldown]);
  return (
    <form
      className="card auth-form password-reset"
      onSubmit={(e) => {
        e.preventDefault();
        void action.run(async () => {
          if (password !== confirm) throw new Error("两次输入的密码不一致。");
          await api("/auth/password/reset", {
            method: "POST",
            body: JSON.stringify({
              email,
              code,
              challenge_id: challenge,
              password,
            }),
          });
          setPassword("");
          setConfirm("");
          setCode("");
          setChallenge("");
          setDone(true);
          await session.load();
        }, "密码已重设，请使用新密码登录。");
      }}
    >
      <h1>{done ? "密码已重设" : "找回密码"}</h1>
      {done ? (
        <>
          <p>原有活动和身份均已保留。所有设备需要用新密码重新登录。</p>
          <Link className="button primary" to={loginUrl}>
            返回登录
          </Link>
        </>
      ) : (
        <>
          <p className="muted">
            通过注册邮箱验证身份。重设密码后，所有设备的旧登录会失效。
          </p>
          <div className="email-field">
            <label htmlFor="reset-email">注册邮箱</label>
            <div className="email-entry">
              <input
                id="reset-email"
                required
                type="email"
                maxLength={254}
                autoComplete="email"
                value={email}
                disabled={mail.pending || action.pending}
                onChange={(e) => {
                  setEmail(e.target.value);
                  setChallenge("");
                  setCode("");
                }}
              />
              <button
                type="button"
                disabled={
                  !ready ||
                  mail.pending ||
                  action.pending ||
                  cooldown > 0 ||
                  !email.includes("@")
                }
                onClick={() =>
                  void mail.run(async () => {
                    const result = await api<any>("/auth/password/code", {
                      method: "POST",
                      body: JSON.stringify({ email }),
                    });
                    setChallenge(result.challenge_id);
                    setCooldown(result.retry_after);
                  }, "如果该邮箱已注册，验证码将发送到邮箱；10 分钟内有效。")
                }
              >
                {mail.pending
                  ? "发送中…"
                  : cooldown
                    ? `${cooldown} 秒后重发`
                    : "发送验证码"}
              </button>
            </div>
          </div>
          {!ready && (
            <p className="muted">邮件服务暂不可用，请稍后重试或联系管理员。</p>
          )}
          <label>
            邮箱验证码
            <input
              required
              autoComplete="one-time-code"
              inputMode="numeric"
              pattern="[0-9]{6}"
              maxLength={6}
              value={code}
              onChange={(e) => setCode(e.target.value)}
            />
          </label>
          <label>
            新密码
            <input
              aria-label="新密码"
              aria-describedby="reset-password-help"
              required
              type="password"
              autoComplete="new-password"
              minLength={10}
              maxLength={200}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <small id="reset-password-help">至少 10 位字符</small>
          </label>
          <label>
            再次输入新密码
            <input
              required
              type="password"
              autoComplete="new-password"
              minLength={10}
              maxLength={200}
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
            />
          </label>
          {confirm && password !== confirm && (
            <p className="error">两次输入的密码不一致。</p>
          )}
          <button
            className="primary"
            disabled={
              !challenge ||
              mail.pending ||
              action.pending ||
              password !== confirm
            }
          >
            {action.pending ? "正在重设…" : "重设密码"}
          </button>
          <Link to={loginUrl}>返回登录</Link>
          <p className="muted">
            游客请在登录页使用恢复码找回身份；旧用户名账号需联系管理员协助。
          </p>
        </>
      )}
    </form>
  );
}
