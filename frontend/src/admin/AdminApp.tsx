import "../admin/admin-extra.css";

import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import {
  Navigate,
  NavLink,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";
import {
  BookOpen,
  CalendarDays,
  ClipboardList,
  FileText,
  LayoutDashboard,
  LogOut,
  Menu,
  ScrollText,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Users,
  Wallet,
  X,
  Map,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { ApiError } from "../shared/api";
import { adminApi, setUnauthorizedHandler } from "./api";
import { errorMessage } from "./api";
import { LoginPage } from "./pages/LoginPage";
import { DashboardPage } from "./pages/DashboardPage";
import { ParticipantsPage } from "./pages/ParticipantsPage";
import { ConsentPage } from "./pages/ConsentPage";
import { RoomsPage } from "./pages/RoomsPage";
import { RoomDetailPage } from "./pages/RoomDetailPage";
import { InstructionsPage } from "./pages/InstructionsPage";
import { TroopProfilesPage } from "./pages/TroopProfilesPage";
import { MapGroupsPage } from "./pages/MapGroupsPage";
import { QuestionnairesPage } from "./pages/QuestionnairesPage";
import { PaymentsPage } from "./pages/PaymentsPage";
import { BulkPaymentsPage } from "./pages/BulkPaymentsPage";
import { AuditPage } from "./pages/AuditPage";
import { SettingsPage } from "./pages/SettingsPage";
import { ErrorNotice, LoadingBlock, UiProvider } from "./ui";
import type { AdminIdentity, AdminMeResponse } from "./types";

interface NavItem {
  key: string;
  label: string;
  to: string;
  icon: LucideIcon;
  end?: boolean;
}

const NAV_ITEMS: NavItem[] = [
  { key: "dashboard", label: "仪表盘", to: "/admin", icon: LayoutDashboard, end: true },
  { key: "participants", label: "被试名单", to: "/admin/participants", icon: Users },
  { key: "consent", label: "知情同意", to: "/admin/consent", icon: FileText },
  { key: "rooms", label: "房间", to: "/admin/rooms", icon: CalendarDays },
  { key: "troop-profiles", label: "兵力方案", to: "/admin/troop-profiles", icon: SlidersHorizontal },
  { key: "map-groups", label: "地图组", to: "/admin/map-groups", icon: Map },
  { key: "instructions", label: "指导语", to: "/admin/instructions", icon: BookOpen },
  { key: "questionnaires", label: "问卷", to: "/admin/questionnaires", icon: ClipboardList },
  { key: "payments", label: "付款", to: "/admin/payments", icon: Wallet },
  { key: "audit", label: "审计", to: "/admin/audit", icon: ScrollText },
  { key: "settings", label: "设置", to: "/admin/settings", icon: Settings },
];

function pageTitle(pathname: string): { title: string; crumb: string } {
  if (pathname === "/admin" || pathname === "/admin/") {
    return { title: "仪表盘", crumb: "总览" };
  }
  if (pathname.startsWith("/admin/rooms/")) {
    return { title: "房间详情", crumb: "房间" };
  }
  const item = NAV_ITEMS.find(
    (entry) => entry.to !== "/admin" && pathname.startsWith(entry.to),
  );
  if (item) return { title: item.label, crumb: "管理" };
  return { title: "管理端", crumb: "管理" };
}

function AdminLayout({
  admin,
  onLogout,
  children,
}: {
  admin: AdminIdentity;
  onLogout: () => void;
  children: ReactNode;
}) {
  const location = useLocation();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const current = pageTitle(location.pathname);

  useEffect(() => {
    setDrawerOpen(false);
  }, [location.pathname]);

  return (
    <div className="admin-root">
      <div className="admin-layout">
        <aside className={`admin-sidebar${drawerOpen ? " open" : ""}`} aria-label="管理端导航">
          <div className="admin-brand">
            <div className="admin-brand-row">
              <ShieldCheck size={20} aria-hidden="true" />
              <span>实验平台</span>
            </div>
            <span className="admin-brand-sub">管理端</span>
          </div>
          <nav className="admin-nav">
            {NAV_ITEMS.map((item) => {
              const Icon = item.icon;
              return (
                <NavLink
                  key={item.key}
                  to={item.to}
                  end={item.end}
                  className={({ isActive }) => (isActive ? "active" : undefined)}
                  data-testid={`nav-${item.key}`}
                >
                  <Icon size={17} aria-hidden="true" />
                  {item.label}
                </NavLink>
              );
            })}
          </nav>
          <div className="admin-sidebar-footer">
            <span className="admin-hint">管理员</span>
            <strong>{admin.username}</strong>
          </div>
        </aside>
        <div
          className={`admin-sidebar-backdrop${drawerOpen ? " open" : ""}`}
          onClick={() => setDrawerOpen(false)}
          aria-hidden="true"
        />
        <div className="admin-main">
          <header className="admin-topbar">
            <div className="admin-topbar-title-group">
              <button
                type="button"
                className="admin-icon-btn admin-mobile-toggle"
                aria-label={drawerOpen ? "关闭菜单" : "打开菜单"}
                onClick={() => setDrawerOpen((value) => !value)}
              >
                {drawerOpen ? <X size={20} /> : <Menu size={20} />}
              </button>
              <div className="admin-topbar-title">
                <span className="admin-topbar-crumb">管理端 / {current.crumb}</span>
                <span>{current.title}</span>
              </div>
            </div>
            <div className="admin-topbar-menu">
              <span>{admin.username}</span>
              <button type="button" className="admin-btn admin-btn-secondary admin-btn-sm" onClick={onLogout}>
                <LogOut size={14} />
                退出
              </button>
            </div>
          </header>
          <main className="admin-content">{children}</main>
        </div>
      </div>
    </div>
  );
}

function SessionLoading() {
  return (
    <div className="admin-root" style={{ display: "grid", placeItems: "center", minHeight: "100dvh" }}>
      <div style={{ width: "min(420px, 90vw)" }}>
        <LoadingBlock rows={3} label="正在验证登录状态" />
      </div>
    </div>
  );
}

function SessionError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="admin-root" style={{ display: "grid", placeItems: "center", minHeight: "100dvh" }}>
      <div style={{ width: "min(480px, 90vw)" }}>
        <div className="admin-card">
          <h1 className="admin-section-title">无法确认登录状态</h1>
          <ErrorNotice message={message} onRetry={onRetry} />
        </div>
      </div>
    </div>
  );
}

function AdminPages() {
  return (
    <Routes>
      <Route index element={<DashboardPage />} />
      <Route path="participants" element={<ParticipantsPage />} />
      <Route path="consent" element={<ConsentPage />} />
      <Route path="rooms" element={<RoomsPage />} />
      <Route path="rooms/:roomId" element={<RoomDetailPage />} />
      <Route path="troop-profiles" element={<TroopProfilesPage />} />
      <Route path="map-groups" element={<MapGroupsPage />} />
      <Route path="instructions" element={<InstructionsPage />} />
      <Route path="questionnaires" element={<QuestionnairesPage />} />
      <Route path="payments" element={<PaymentsPage />} />
      <Route path="payments/bulk" element={<BulkPaymentsPage />} />
      <Route path="audit" element={<AuditPage />} />
      <Route path="settings" element={<SettingsPage />} />
      <Route path="*" element={<Navigate to="/admin" replace />} />
    </Routes>
  );
}

export default function AdminApp() {
  const location = useLocation();
  const navigate = useNavigate();
  const loginPath = location.pathname.replace(/\/+$/, "") === "/admin/login";
  const [admin, setAdmin] = useState<AdminIdentity | null>(null);
  const [checking, setChecking] = useState(true);
  const [sessionError, setSessionError] = useState<string | null>(null);
  const [retryNonce, setRetryNonce] = useState(0);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setAdmin(null);
      setChecking(false);
      navigate("/admin/login", { replace: true });
    });
    return () => setUnauthorizedHandler(null);
  }, [navigate]);

  useEffect(() => {
    if (loginPath) {
      setChecking(false);
      return;
    }
    if (admin !== null) {
      setChecking(false);
      return;
    }
    let cancelled = false;
    setChecking(true);
    setSessionError(null);
    adminApi
      .get<AdminMeResponse>("/me")
      .then((response) => {
        if (cancelled) return;
        setAdmin(response.admin);
        setChecking(false);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setChecking(false);
        if (error instanceof ApiError && error.status === 401) {
          setAdmin(null);
          navigate("/admin/login", { replace: true });
          return;
        }
        setSessionError(errorMessage(error));
      });
    return () => {
      cancelled = true;
    };
  }, [loginPath, admin, navigate, retryNonce]);

  async function handleLogout() {
    try {
      await adminApi.post("/logout");
    } catch {
      // 会话已经失效时仍然返回登录页
    }
    setAdmin(null);
    navigate("/admin/login", { replace: true });
  }

  return (
    <UiProvider>
      {loginPath ? (
        <Routes>
          <Route
            path="login"
            element={
              admin ? (
                <Navigate to="/admin" replace />
              ) : (
                <LoginPage onSuccess={(identity) => setAdmin(identity)} />
              )
            }
          />
          <Route path="*" element={<Navigate to="/admin/login" replace />} />
        </Routes>
      ) : checking ? (
        <SessionLoading />
      ) : sessionError ? (
        <SessionError
          message={sessionError}
          onRetry={() => setRetryNonce((value) => value + 1)}
        />
      ) : admin === null ? (
        <Navigate to="/admin/login" replace />
      ) : (
        <AdminLayout admin={admin} onLogout={handleLogout}>
          <AdminPages />
        </AdminLayout>
      )}
    </UiProvider>
  );
}
