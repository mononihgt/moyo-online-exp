import { useState, type FormEvent } from "react";
import { LogIn } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";

import { ApiError, api } from "../shared/api";
import { SessionNotice } from "./session";
import type { LoginResponse } from "./apiTypes";

export default function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [notice] = useState(
    (location.state as { notice?: string } | null)?.notice ?? "",
  );

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (submitting) return;
    const trimmedName = name.trim();
    const trimmedPhone = phone.trim();
    if (trimmedName === "" || trimmedPhone === "") {
      setError("请填写姓名和手机号。");
      return;
    }
    setError("");
    setSubmitting(true);
    try {
      const response = await api<LoginResponse>("/api/login", {
        method: "POST",
        body: JSON.stringify({ name: trimmedName, phone: trimmedPhone }),
      });
      navigate(response.me.consentRequired ? "/consent" : "/", { replace: true });
    } catch (caught: unknown) {
      if (caught instanceof ApiError) {
        if (caught.status === 401) {
          setError("姓名或手机号不正确");
        } else {
          setError(caught.message || "登录失败，请稍后重试。");
        }
      } else {
        setError("网络异常，请检查连接后重试。");
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="p-center-page">
      <main className="p-login-card" aria-labelledby="login-title">
        <p className="p-login-logo">Moyo 实验平台</p>
        <h1 className="p-title-sm" id="login-title">
          登录实验平台
        </h1>
        <p className="p-subtitle">
          请使用报名时登记的姓名和手机号登录。手机号仅用于身份核对和付款，不会完整显示。
        </p>
        <SessionNotice text={notice} />
        {error !== "" ? (
          <div className="p-banner p-banner-error" id="login-error" role="alert">
            {error}
          </div>
        ) : null}
        <form onSubmit={handleSubmit}>
          <div className="p-field">
            <label className="p-label" htmlFor="login-name">
              姓名
            </label>
            <input
              id="login-name"
              data-testid="login-name"
              className="p-input"
              type="text"
              name="name"
              autoComplete="name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              aria-invalid={error !== "" ? true : undefined}
              aria-describedby={error !== "" ? "login-error" : undefined}
              required
            />
          </div>
          <div className="p-field">
            <label className="p-label" htmlFor="login-phone">
              手机号
            </label>
            <input
              id="login-phone"
              data-testid="login-phone"
              className="p-input"
              type="tel"
              name="phone"
              inputMode="tel"
              autoComplete="tel"
              value={phone}
              onChange={(event) => setPhone(event.target.value)}
              aria-invalid={error !== "" ? true : undefined}
              aria-describedby={error !== "" ? "login-error" : undefined}
              required
            />
          </div>
          <button
            type="submit"
            data-testid="login-submit"
            className="p-btn p-btn-primary p-btn-block"
            disabled={submitting}
          >
            <LogIn size={18} aria-hidden="true" />
            {submitting ? "正在登录…" : "登录"}
          </button>
        </form>
        <p className="p-muted p-login-help">
          如无法登录，请确认姓名和手机号与名单一致，或联系实验组织者。
        </p>
      </main>
    </div>
  );
}
