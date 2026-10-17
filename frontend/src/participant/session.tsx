import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { Navigate, Outlet, useLocation, useNavigate } from "react-router-dom";

import { ApiError, api } from "../shared/api";
import type { ParticipantMe } from "../shared/types";
import { formatUnknownError } from "./apiTypes";
import type { MeResponse } from "./apiTypes";

interface SessionContextValue {
  me: ParticipantMe;
  request: <T>(path: string, options?: RequestInit) => Promise<T>;
  refreshMe: () => Promise<ParticipantMe>;
  updateMe: (me: ParticipantMe) => void;
  logout: () => Promise<void>;
}

const SessionContext = createContext<SessionContextValue | null>(null);

export function useSession(): SessionContextValue {
  const value = useContext(SessionContext);
  if (value === null) {
    throw new Error("SessionContext 未初始化");
  }
  return value;
}

function LoadingScreen() {
  return (
    <div className="p-center-page">
      <div className="p-card p-span-loading" role="status">
        正在加载…
      </div>
    </div>
  );
}

export function ParticipantGuard() {
  const navigate = useNavigate();
  const location = useLocation();
  const [me, setMe] = useState<ParticipantMe | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [unauthenticated, setUnauthenticated] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setLoadError("");
    api<MeResponse>("/api/me")
      .then((response) => {
        if (!alive) return;
        setMe(response.me);
        setUnauthenticated(false);
      })
      .catch((error: unknown) => {
        if (!alive) return;
        if (error instanceof ApiError && error.status === 401) {
          setUnauthenticated(true);
          return;
        }
        setLoadError(formatUnknownError(error, "无法加载账号信息，请稍后重试。"));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [reloadToken]);

  const request = useCallback(
    async function requestApi<T>(path: string, options?: RequestInit): Promise<T> {
      try {
        return await api<T>(path, options);
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          setUnauthenticated(true);
          navigate("/login", {
            replace: true,
            state: { notice: "登录已过期，请重新登录。" },
          });
        }
        throw error;
      }
    },
    [navigate],
  );

  const refreshMe = useCallback(async () => {
    const response = await request<MeResponse>("/api/me");
    setMe(response.me);
    return response.me;
  }, [request]);

  const updateMe = useCallback((next: ParticipantMe) => {
    setMe(next);
  }, []);

  const logout = useCallback(async () => {
    await api("/api/logout", { method: "POST" });
    navigate("/login", { replace: true, state: { notice: "你已退出登录。" } });
  }, [navigate]);

  const value = useMemo<SessionContextValue | null>(() => {
    if (me === null) return null;
    return { me, request, refreshMe, updateMe, logout };
  }, [me, request, refreshMe, updateMe, logout]);

  if (unauthenticated) {
    return (
      <Navigate
        to="/login"
        replace
        state={{ notice: "登录已过期，请重新登录。" }}
      />
    );
  }

  if (loading) {
    return <LoadingScreen />;
  }

  if (loadError !== "" || value === null || me === null) {
    return (
      <div className="p-center-page">
        <div className="p-card p-load-card">
          <h1 className="p-title-sm">无法加载账号信息</h1>
          <div className="p-banner p-banner-error" role="alert">
            {loadError || "请稍后重试。"}
          </div>
          <div className="p-btn-row">
            <button
              type="button"
              className="p-btn p-btn-primary"
              onClick={() => setReloadToken((token) => token + 1)}
            >
              重新加载
            </button>
            <button
              type="button"
              className="p-btn p-btn-secondary"
              onClick={() => navigate("/login", { replace: true })}
            >
              返回登录
            </button>
          </div>
        </div>
      </div>
    );
  }

  const consentTarget = me.consentRequired && location.pathname !== "/consent";
  const homeTarget = !me.consentRequired && location.pathname === "/consent";

  return (
    <SessionContext.Provider value={value}>
      {consentTarget ? (
        <Navigate to="/consent" replace />
      ) : homeTarget ? (
        <Navigate to="/" replace />
      ) : (
        <Outlet />
      )}
    </SessionContext.Provider>
  );
}

export function SessionNotice({ text }: { text: string }) {
  if (text === "") return null;
  return (
    <div className="p-banner p-banner-info" role="status">
      {text}
    </div>
  );
}

export function PageFrame({
  children,
  narrow = false,
}: {
  children: ReactNode;
  narrow?: boolean;
}) {
  return (
    <div className="p-page">
      <main className={narrow ? "p-shell-narrow" : "p-shell"}>{children}</main>
    </div>
  );
}
