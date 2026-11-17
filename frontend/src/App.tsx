import { useState, type ReactNode } from "react";
import {
  Link,
  NavLink,
  Navigate,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import { RecoveryNotice, useSession } from "./session";
import { Icon, ShuttleMark } from "./visuals";
import AdminVenuesPage from "./pages/AdminVenuesPage";
import HomePage from "./pages/HomePage";
import TimePage from "./pages/TimePage";
import VenuePage from "./pages/VenuePage";
import ActivityPage from "./pages/ActivityPage";
import BillPage from "./pages/BillPage";
import ProfilePage from "./pages/ProfilePage";
import AuthPage from "./pages/AuthPage";
import PasswordResetPage from "./pages/PasswordResetPage";
import InvitePage from "./pages/InvitePage";
import BotLoginPage from "./pages/BotLoginPage";
function Protected({ children }: { children: ReactNode }) {
  const { user } = useSession(),
    location = useLocation();
  return user ? (
    children
  ) : (
    <Navigate
      to={`/login?next=${encodeURIComponent(location.pathname + location.search)}`}
      replace
    />
  );
}
export default function App() {
  const { user, ready } = useSession(),
    location = useLocation(),
    [menu, setMenu] = useState(false);
  if (!ready)
    return (
      <p className="loading" role="status">
        正在打开 ShuttleUp…
      </p>
    );
  return (
    <div className="app-shell">
      <header className="mobile-bar">
        <Link className="brand" to="/">
          <ShuttleMark /> ShuttleUp
        </Link>
        <button
          aria-label="展开导航"
          aria-expanded={menu}
          onClick={() => setMenu(!menu)}
        >
          <Icon name="menu" />
        </button>
      </header>
      <aside className={`sidebar ${menu ? "open" : ""}`}>
        <Link className="brand" to="/">
          <ShuttleMark />
          <span>
            ShuttleUp<small>一起上场</small>
          </span>
        </Link>
        <p className="nav-label">球友工作台</p>
        <nav aria-label="主导航" onClick={() => setMenu(false)}>
          <NavLink
            to="/"
            end
            className={({ isActive }) =>
              isActive ||
              /^\/a\/[^/]+(?:\/bill)?$/.test(location.pathname) ||
              (location.pathname === "/me/time" &&
                new URLSearchParams(location.search).has("activity_id"))
                ? "active"
                : ""
            }
          >
            <Icon name="activity" />
            约球活动
          </NavLink>
          <NavLink to="/venues">
            <Icon name="venue" />
            可用场地
          </NavLink>
          <NavLink
            to="/me/time"
            className={({ isActive }) =>
              isActive &&
              !new URLSearchParams(location.search).has("activity_id")
                ? "active"
                : ""
            }
          >
            <Icon name="time" />
            空闲时间
          </NavLink>
          <NavLink
            to="/bills"
            className={({ isActive }) => (isActive ? "active" : "")}
          >
            <Icon name="bill" />
            全部活动账单
          </NavLink>
          <NavLink to="/me" end>
            <Icon name="profile" />
            个人设置
          </NavLink>
          {user?.is_admin && (
            <NavLink to="/admin/venues">
              <Icon name="admin" />
              场馆管理
            </NavLink>
          )}
        </nav>
        <div className="sidebar-note">
          <span className="sidebar-court" aria-hidden="true" />
          <p>时间约好，球场见。</p>
        </div>
        <Link className="account" to={user ? "/me" : "/login"}>
          <span className="avatar">
            {user?.display_name.slice(0, 1) || "↗"}
          </span>
          <span>
            {user?.display_name || "登录 / 注册"}
            <small>
              {user
                ? user.is_admin
                  ? "系统管理员"
                  : user.username || user.email
                    ? "账号已登录"
                    : "游客 · 可升级账号"
                : "保存你的活动与时间"}
            </small>
          </span>
        </Link>
      </aside>
      <main className="main-content" key={location.pathname + location.search}>
        <RecoveryNotice />
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route
            path="/venues"
            element={
              <Protected>
                <VenuePage />
              </Protected>
            }
          />
          <Route
            path="/admin/venues"
            element={
              <Protected>
                <AdminVenuesPage />
              </Protected>
            }
          />
          <Route path="/login" element={<AuthPage />} />
          <Route path="/forgot-password" element={<PasswordResetPage />} />
          <Route path="/bot-login" element={<BotLoginPage />} />
          <Route path="/i/:token" element={<InvitePage />} />
          <Route
            path="/me/time"
            element={
              <Protected>
                <TimePage />
              </Protected>
            }
          />
          <Route
            path="/a/:id"
            element={
              <Protected>
                <ActivityPage />
              </Protected>
            }
          />
          <Route
            path="/a/:id/bill"
            element={
              <Protected>
                <BillPage />
              </Protected>
            }
          />
          <Route
            path="/bills"
            element={
              <Protected>
                <HomePage bills />
              </Protected>
            }
          />
          <Route
            path="/me"
            element={
              <Protected>
                <ProfilePage />
              </Protected>
            }
          />
          <Route
            path="*"
            element={
              <div className="card empty">
                <h1>页面不存在</h1>
                <Link to="/">返回活动工作台</Link>
              </div>
            }
          />
        </Routes>
      </main>
    </div>
  );
}
