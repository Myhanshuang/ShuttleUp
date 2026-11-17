import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useSession } from "../session";
import { send, useAction } from "../ui";
export default function BotLoginPage() {
  const [token] = useState(() => {
      const value = new URLSearchParams(location.hash.slice(1)).get("token");
      history.replaceState(null, "", location.pathname);
      return value;
    }),
    session = useSession(),
    navigate = useNavigate(),
    action = useAction();
  return (
    <div className="card invite-card stack">
      <h1>在网页继续约球</h1>
      <p>
        登录后，使用你在 Bot 中的同一身份，继续查看活动、编辑时间和处理账单。
      </p>
      {session.user && (
        <p className="notice">
          当前登录为 {session.user.display_name}，继续后将切换为链接对应的 Bot
          身份。
        </p>
      )}
      {action.feedback}
      {token ? (
        <button
          className="primary"
          disabled={action.pending}
          onClick={() =>
            action.run(async () => {
              await api("/auth/bot-login", send({ token }));
              await session.load();
              navigate("/", { replace: true });
            })
          }
        >
          确认登录 Bot 身份
        </button>
      ) : (
        <p>请私聊 Bot 发送 /羽球 网页，获取新的登录链接。</p>
      )}
    </div>
  );
}
