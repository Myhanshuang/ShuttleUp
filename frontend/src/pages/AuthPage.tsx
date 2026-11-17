import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { CourtIllustration } from "../visuals";
import { api } from "../api/client";
import { useSession } from "../session";
import { useAction } from "../ui";
export default function AuthPage({ upgrade = false }: { upgrade?: boolean }) {
  const [mode, setMode] = useState(upgrade ? "register" : "login"),
    [username, setUsername] = useState(""),
    [password, setPassword] = useState(""),
    [name, setName] = useState(""),
    [recovery, setRecovery] = useState("");
  const [email, setEmail] = useState(""),
    [code, setCode] = useState(""),
    [challenge, setChallenge] = useState(""),
    [cooldown, setCooldown] = useState(0),
    [mailReady, setMailReady] = useState<boolean | null>(null);
  const mailAction = useAction();
  useEffect(() => {
    api<{ email_registration: boolean }>("/auth/options")
      .then((data) => setMailReady(data.email_registration))
      .catch(() => setMailReady(false));
  }, []);
  useEffect(() => {
    if (!cooldown) return;
    const timer = window.setTimeout(() => setCooldown(cooldown - 1), 1000);
    return () => window.clearTimeout(timer);
  }, [cooldown]);
  const emailRegister = mode === "register";
  const session = useSession(),
    navigate = useNavigate(),
    location = useLocation(),
    action = useAction();
  const next = new URLSearchParams(location.search).get("next") || "/";
  return (
    <div className="auth-layout">
      <div className="auth-story">
        <h1>
          下一场球，
          <br />
          一起上场。
        </h1>
        <p>
          约好共同的时间，
          <br />
          把球友聚到同一片场地。
        </p>
        <CourtIllustration />
        <div className="auth-story-caption">从发起邀约，到打完 AA。</div>
      </div>
      <form
        className="card auth-form"
        onSubmit={(e) => {
          e.preventDefault();
          void action.run(async () => {
            const result = await api<{ recovery_code?: string }>(
              mode === "recover"
                ? "/auth/guest/recover"
                : emailRegister
                  ? "/auth/email/register"
                  : `/auth/${mode}`,
              {
                method: "POST",
                body: JSON.stringify(
                  mode === "recover"
                    ? { recovery_code: recovery.trim() }
                    : emailRegister
                      ? {
                          email,
                          code,
                          challenge_id: challenge,
                          password,
                          display_name: name,
                        }
                      : mode === "guest"
                        ? { display_name: name }
                        : {
                            username,
                            password,
                          },
                ),
              },
            );
            await session.load();
            if (result.recovery_code)
              session.setRecoveryCode(result.recovery_code);
            navigate(
              next.startsWith("/") && !next.startsWith("//") ? next : "/",
              { replace: true },
            );
          });
        }}
      >
        <h2>
          {mode === "login"
            ? "登录 ShuttleUp"
            : mode === "register"
              ? upgrade
                ? "升级为账号"
                : "创建账号"
              : mode === "recover"
                ? "恢复游客身份"
                : "以游客身份继续"}
        </h2>
        {mode !== "guest" && (
          <div className="segmented">
            <button
              type="button"
              className={mode === "login" ? "selected" : ""}
              onClick={() => setMode("login")}
            >
              登录
            </button>
            <button
              type="button"
              className={mode === "register" ? "selected" : ""}
              onClick={() => setMode("register")}
            >
              注册
            </button>
          </div>
        )}
        {(mode === "guest" || mode === "register") && (
          <label>
            你的昵称
            <input
              required={mode === "guest" || emailRegister}
              value={name}
              maxLength={40}
              onChange={(e) => setName(e.target.value)}
              autoComplete="nickname"
            />
          </label>
        )}
        {mode === "recover" && (
          <label>
            游客恢复码
            <input
              aria-label="游客恢复码"
              required
              minLength={32}
              maxLength={128}
              autoComplete="off"
              value={recovery}
              onChange={(e) => setRecovery(e.target.value)}
            />
            <small>
              恢复后保留原有活动和时间，旧设备会退出登录，并生成新的恢复码。
            </small>
          </label>
        )}
        {(mode === "login" || mode === "register") && (
          <>
            {emailRegister ? (
              <>
                <div className="email-field">
                  <label htmlFor="registration-email">邮箱</label>
                  <div className="email-entry">
                    <input
                      id="registration-email"
                      type="email"
                      disabled={mailAction.pending}
                      required
                      maxLength={254}
                      autoComplete="email"
                      value={email}
                      onChange={(e) => {
                        setEmail(e.target.value);
                        setChallenge("");
                        setCode("");
                      }}
                    />
                    <button
                      type="button"
                      disabled={
                        !mailReady ||
                        mailAction.pending ||
                        cooldown > 0 ||
                        !email.includes("@")
                      }
                      onClick={() =>
                        void mailAction.run(async () => {
                          const result = await api<{
                            challenge_id: string;
                            retry_after: number;
                          }>("/auth/email/code", {
                            method: "POST",
                            body: JSON.stringify({ email }),
                          });
                          setChallenge(result.challenge_id);
                          setCooldown(result.retry_after);
                        }, "验证码已发送，请查看邮箱；10 分钟内有效。")
                      }
                    >
                      {mailAction.pending
                        ? "正在发送…"
                        : cooldown > 0
                          ? `${cooldown} 秒后可重发`
                          : "发送验证码"}
                    </button>
                  </div>
                </div>
                {mailReady === false && (
                  <p role="status" className="muted">
                    管理员尚未配置邮件发送服务，暂时无法获取验证码。
                  </p>
                )}
                {mailAction.feedback}
                <label>
                  邮箱验证码
                  <input
                    required
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    pattern="[0-9]{6}"
                    maxLength={6}
                    value={code}
                    onChange={(e) => setCode(e.target.value)}
                  />
                </label>
              </>
            ) : (
              <label>
                用户名或邮箱
                <input
                  required
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  autoComplete="username"
                />
              </label>
            )}
            <label>
              密码
              <input
                aria-label="密码"
                required
                minLength={mode === "register" ? 10 : undefined}
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete={
                  mode === "login" ? "current-password" : "new-password"
                }
              />
              {mode === "register" && <small>至少 10 位字符</small>}
            </label>
          </>
        )}
        {action.feedback}
        {mode === "login" && (
          <Link
            className="forgot-password"
            to={`/forgot-password?next=${encodeURIComponent(next)}`}
          >
            忘记密码？
          </Link>
        )}
        <button
          className="primary"
          disabled={
            action.pending ||
            (emailRegister && (!challenge || mailAction.pending))
          }
        >
          {action.pending
            ? "请稍候…"
            : mode === "login"
              ? "登录"
              : mode === "register"
                ? "创建账号"
                : mode === "recover"
                  ? "恢复身份"
                  : "确认以游客继续"}
        </button>
        {mode === "guest" ? (
          <>
            <p className="muted">
              游客身份保存在当前浏览器，之后可在个人设置升级为账号。
            </p>
            <button
              type="button"
              className="text-button"
              onClick={() => setMode("login")}
            >
              返回账号登录
            </button>
          </>
        ) : (
          !upgrade && (
            <button
              type="button"
              className="text-button"
              onClick={() => setMode("guest")}
            >
              暂不注册，以游客身份继续
            </button>
          )
        )}
        {mode === "login" && (
          <button
            type="button"
            className="text-button"
            onClick={() => setMode("recover")}
          >
            用恢复码找回游客身份
          </button>
        )}
        <Link to="/">返回活动工作台</Link>
      </form>
    </div>
  );
}
