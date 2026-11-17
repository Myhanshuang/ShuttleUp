import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { api, setCsrf } from "./api/client";
export interface User {
  id: string;
  display_name: string;
  username: string | null;
  email?: string | null;
  is_admin: boolean;
  timezone: string;
  version: number;
}
const Session = createContext<{
  user: User | null;
  ready: boolean;
  load: () => Promise<void>;
  setRecoveryCode: (code: string) => void;
  recoveryCode: string;
}>({ user: null, ready: false, load: async () => {}, setRecoveryCode: () => {}, recoveryCode: "" });
export function SessionProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null),
    [ready, setReady] = useState(false),
    [error, setError] = useState(""),
    [recoveryCode, setRecoveryCode] = useState("");
  async function load() {
    const data = await api<{ user: User | null; csrf_token: string | null }>(
      "/session",
    );
    setUser(data.user);
    if (!data.user || data.user.username || data.user.email) setRecoveryCode("");
    setCsrf(data.csrf_token);
    setReady(true);
  }
  useEffect(() => {
    load().catch((e) => setError(e.message));
    const timer = window.setInterval(() => { void load().catch(() => {}); }, 60 * 60 * 1000);
    return () => window.clearInterval(timer);
  }, []);
  if (error)
    return (
      <div role="alert" className="card">
        {error}
        <button
          onClick={() => {
            setError("");
            void load().catch((e) => setError(e.message));
          }}
        >
          重试
        </button>
      </div>
    );
  return (
    <Session.Provider value={{ user, ready, load, setRecoveryCode, recoveryCode }}>

      {children}
    </Session.Provider>
  );
}
export const useSession = () => useContext(Session);

export function RecoveryNotice() {
  const {recoveryCode, setRecoveryCode} = useSession();
  return (<> {recoveryCode && <aside className="card stack" aria-label="保存游客恢复码">
        <strong>请保存你的新游客恢复码</strong>
        <p>换设备或清理浏览器后，可在登录页恢复同一身份。此码只显示这一次，使用后会更换，请像密码一样保管。</p>
        <label>游客恢复码<input readOnly value={recoveryCode} onFocus={e => e.target.select()} /></label>
        <button onClick={() => setRecoveryCode("")}>我已保存恢复码</button>
      </aside>} </>);
}
