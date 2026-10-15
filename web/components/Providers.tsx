"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";

interface UserInfo {
  /** Empty when nobody is signed in (Phase 1 is readable without an account). */
  email: string;
  authDisabled: boolean;
  /** May open Phase 2 (account listed in PHASE2_EMAILS). */
  phase2: boolean;
}

const UserContext = createContext<UserInfo>({ email: "", authDisabled: false, phase2: false });
export const useUser = () => useContext(UserContext);

interface ToastOptions {
  /** Shows a "Hoàn tác" button that runs this callback. */
  undo?: () => void;
  tone?: "info" | "error";
  ms?: number;
}
interface ToastState extends ToastOptions {
  id: number;
  message: string;
}

const ToastContext = createContext<(message: string, opts?: ToastOptions) => void>(() => {});
export const useToast = () => useContext(ToastContext);

/** Fired after any change to an item so other widgets (nav badge) can refresh. */
export const CHANGED_EVENT = "radar:changed";
export function notifyChanged() {
  if (typeof window !== "undefined") window.dispatchEvent(new Event(CHANGED_EVENT));
}

export function Providers({ email, authDisabled, phase2, children }: { email: string; authDisabled: boolean; phase2: boolean; children: React.ReactNode }) {
  const [toast, setToast] = useState<ToastState | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const show = useCallback((message: string, opts: ToastOptions = {}) => {
    if (timer.current) clearTimeout(timer.current);
    const id = Date.now();
    setToast({ id, message, ...opts });
    timer.current = setTimeout(() => setToast((t) => (t?.id === id ? null : t)), opts.ms ?? (opts.undo ? 6000 : 4000));
  }, []);

  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  return (
    <UserContext.Provider value={{ email, authDisabled, phase2 }}>
      <ToastContext.Provider value={show}>
        {children}
        <div aria-live="polite" role="status">
          {toast && (
            <div className={`toast${toast.tone === "error" ? " error" : ""}`}>
              <span>{toast.message}</span>
              {toast.undo && (
                <button
                  type="button"
                  onClick={() => {
                    const undo = toast.undo;
                    setToast(null);
                    undo?.();
                  }}
                >
                  Hoàn tác
                </button>
              )}
            </div>
          )}
        </div>
      </ToastContext.Provider>
    </UserContext.Provider>
  );
}
