import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useSession } from "../session";
import { Heading, send, useAction } from "../ui";
import AuthPage from "./AuthPage";
export default function ProfilePage() {
  const session = useSession(),
    navigate = useNavigate(),
    action = useAction(),
    [code, setCode] = useState(""),
    [name, setName] = useState(session.user?.display_name || ""),
    [upgrade, setUpgrade] = useState(false);
  if (upgrade) return <AuthPage upgrade />;
  return (
    <>
      <Heading eyebrow="账号与偏好" title="个人设置" />
      {action.feedback}
      {session.user?.is_admin && <p className="notice">系统管理员 · <Link to="/admin/venues">进入场馆管理</Link></p>}
      <div className="activity-grid">
        <form
          className="card stack"
          onSubmit={(e) => {
            e.preventDefault();
            void action.run(async () => {
              await api(
                "/me",
                send(
                  {
                    display_name: name,
                    timezone: session.user!.timezone,
                    expected_version: session.user!.version,
                  },
                  "PATCH",
                ),
              );
              await session.load();
            }, "昵称已更新");
          }}
        >
          <h2>
            {session.user?.username ? `@${session.user.username}` : session.user?.email || "游客身份"}
          </h2>
          <label>
            显示昵称
            <input
              required
              maxLength={40}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
          <button disabled={action.pending}>保存资料</button>
          {!session.user?.username && !session.user?.email && (
            <button
              type="button"
              className="primary"
              onClick={() => setUpgrade(true)}
            >
              绑定邮箱，保留身份和已有活动
            </button>
          )}
        </form>
        {!session.user?.username && !session.user?.email && <article className="card stack">
          <h2>保留游客身份</h2>
          <p>绑定邮箱后可随时登录同一身份；活动、空闲时间和账单都会保留。暂不绑定时，请保存恢复码。</p>
          <p className="muted">同一浏览器持续使用会自动续期。重新生成恢复码后，之前保存的码立即失效。</p>
          <button disabled={action.pending} onClick={() => void action.run(async () => {
            const result = await api<{recovery_code: string}>("/me/guest-recovery", send({}));
            session.setRecoveryCode(result.recovery_code);
          })}>生成新的游客恢复码</button>
          <button onClick={() => setUpgrade(true)}>绑定邮箱</button>
        </article>}
        <article className="card stack">
          <h2>AstrBot 群聊入口</h2>
          <p>
            在群里 @Bot 发送「/绑定身份 昵称」可绑定当前 QQ 的身份；发送「/发起约球」即可创建活动，其他球友直接发送「/羽球
            加入」。无需先在网页注册。
          </p>
          <p className="muted">
            如果你已有网页账号，可以在首次使用 Bot 前绑定，让两端使用同一身份。
          </p>
          <button
            disabled={action.pending}
            onClick={() =>
              action.run(async () =>
                setCode((await api<any>("/me/bot-bind-token", send({}))).code),
              )
            }
          >
            生成可选账号绑定码
          </button>
          {code && (
            <div className="notice">
              <strong>/羽球 绑定 {code}</strong>
              <p>请私聊 Bot 发送，10 分钟内有效。</p>
            </div>
          )}
        </article>
      </div>
      <button
        className="danger"
        disabled={action.pending}
        onClick={() =>
          action.run(async () => {
            await api("/auth/logout", { method: "POST" });
            await session.load();
            navigate("/login");
          })
        }
      >
        退出登录
      </button>
    </>
  );
}
