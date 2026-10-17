import { useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Loader2, LockKeyhole, ShieldCheck } from "lucide-react";
import { adminApi, errorMessage } from "../api";
import type { AdminIdentity, AdminMeResponse } from "../types";

export function LoginPage({ onSuccess }: { onSuccess: (admin: AdminIdentity) => void }) {
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!username.trim() || !password) {
      setError("请输入用户名和密码");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const response = await adminApi.post<AdminMeResponse>("/login", {
        username: username.trim(),
        password,
      });
      onSuccess(response.admin);
      navigate("/admin", { replace: true });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="admin-login-page">
      <form className="admin-login-card" onSubmit={handleSubmit}>
        <div className="admin-brand-mark">
          <ShieldCheck size={20} />
        </div>
        <h1 className="admin-page-title" style={{ fontSize: "1.5rem", marginBottom: "8px" }}>
          实验平台管理端
        </h1>
        <p className="admin-page-subtitle" style={{ marginBottom: "24px" }}>
          使用主试账号登录，管理被试、房间与数据。
        </p>
        <div className="admin-field">
          <label className="admin-label" htmlFor="admin-username">
            用户名
          </label>
          <input
            id="admin-username"
            className="admin-input"
            autoComplete="username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            data-testid="admin-login-username"
          />
        </div>
        <div className="admin-field">
          <label className="admin-label" htmlFor="admin-password">
            密码
          </label>
          <input
            id="admin-password"
            className="admin-input"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            data-testid="admin-login-password"
          />
        </div>
        {error ? (
          <div className="admin-error" role="alert" style={{ marginBottom: "12px" }}>
            {error}
          </div>
        ) : null}
        <button
          type="submit"
          className="admin-btn admin-btn-primary admin-login-submit"
          disabled={submitting}
          data-testid="admin-login-submit"
        >
          {submitting ? <Loader2 size={16} className="admin-spin" /> : <LockKeyhole size={16} />}
          {submitting ? "登录中" : "登录"}
        </button>
      </form>
    </div>
  );
}
