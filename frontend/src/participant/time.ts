import { useEffect, useRef, useState } from "react";

export function useNow(intervalMs = 250, active = true): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(timer);
  }, [intervalMs, active]);
  return now;
}

export function secondsLeft(deadline: string | null | undefined, now: number, offsetMs: number): number | null {
  if (!deadline) return null;
  const target = Date.parse(deadline);
  if (Number.isNaN(target)) return null;
  return Math.max(0, Math.ceil((target - (now + offsetMs)) / 1000));
}

export function useHeldCountdown(
  deadline: string | null,
  now: number,
  offsetMs: number,
  fallbackSeconds: number,
): { remaining: number; paused: boolean } {
  const lastRef = useRef<number>(fallbackSeconds);
  const raw = secondsLeft(deadline, now, offsetMs);
  if (raw !== null) {
    lastRef.current = raw;
  }
  if (deadline === null) {
    return { remaining: lastRef.current, paused: true };
  }
  return { remaining: raw ?? fallbackSeconds, paused: false };
}

export function formatClock(totalSeconds: number): string {
  const safe = Math.max(0, Math.floor(totalSeconds));
  const minutes = Math.floor(safe / 60);
  const seconds = safe % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

export function formatSocketUrl(): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/room`;
}

export function exitFullscreenSilently(): void {
  if (typeof document === "undefined") return;
  if (document.fullscreenElement && typeof document.exitFullscreen === "function") {
    void document.exitFullscreen().catch(() => undefined);
  }
}
