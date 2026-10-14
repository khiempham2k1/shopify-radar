"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

/** FastAPI errors are `{detail: "..."}`; validation errors are `{detail: [{msg, loc}]}`. */
function detailText(data: unknown, status: number): string {
  const detail = (data as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string" && detail) return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((d) => {
        const e = d as { msg?: string; loc?: unknown[] };
        const where = Array.isArray(e.loc) ? e.loc.filter((x) => x !== "body").join(".") : "";
        return [where, e.msg].filter(Boolean).join(": ");
      })
      .filter(Boolean);
    if (parts.length) return parts.join("; ");
  }
  if (status === 401) return "Chưa đăng nhập hoặc phiên đã hết hạn. Tải lại trang để đăng nhập.";
  if (status >= 500) return `Máy chủ gặp lỗi (${status}). Thử lại sau ít phút.`;
  return `Yêu cầu không thành công (${status}).`;
}

type Method = "GET" | "POST" | "PATCH" | "PUT" | "DELETE";

/** Calls the FastAPI backend through the Next.js proxy at /api/radar/<path>. */
export async function api<T>(path: string, method: Method = "GET", body?: unknown, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api/radar/${path.replace(/^\/+/, "")}`, {
      method,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
      signal,
    });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw new ApiError("Không kết nối được tới máy chủ. Kiểm tra mạng rồi thử lại.", 0);
  }
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  if (!res.ok) throw new ApiError(detailText(data, res.status), res.status);
  return data as T;
}

export function errorText(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return "Đã có lỗi xảy ra.";
}

export interface ApiState<T> {
  data: T | undefined;
  error: string | null;
  loading: boolean;
  reload: (opts?: { silent?: boolean }) => void;
  setData: React.Dispatch<React.SetStateAction<T | undefined>>;
}

/** Loads `path` (null = don't load) and reloads whenever it changes. */
export function useApi<T>(path: string | null): ApiState<T> {
  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(path !== null);
  const [tick, setTick] = useState(0);
  const silentRef = useRef(false);

  useEffect(() => {
    if (path === null) return;
    const ctrl = new AbortController();
    if (!silentRef.current) setLoading(true);
    silentRef.current = false;
    setError(null);
    api<T>(path, "GET", undefined, ctrl.signal)
      .then((d) => {
        setData(d);
        setLoading(false);
      })
      .catch((err) => {
        if ((err as Error).name === "AbortError") return;
        setError(errorText(err));
        setLoading(false);
      });
    return () => ctrl.abort();
  }, [path, tick]);

  const reload = useCallback((opts?: { silent?: boolean }) => {
    silentRef.current = Boolean(opts?.silent);
    setTick((t) => t + 1);
  }, []);

  return { data, error, loading, reload, setData };
}
