import { useEffect, useState } from "react";

// MVP-only client-side auth. Replace with Entra ID / OAuth before
// exposing to non-localhost traffic. See README.
const AUTH_KEY = "bank-arch.auth.user";

export type AuthUser = {
  employee_id: string;
  signed_in_at: string; // ISO
};

export function loadAuth(): AuthUser | null {
  try {
    const raw = localStorage.getItem(AUTH_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as AuthUser;
  } catch {
    return null;
  }
}

export function saveAuth(user: AuthUser) {
  localStorage.setItem(AUTH_KEY, JSON.stringify(user));
  window.dispatchEvent(new Event("bank-arch:auth"));
}

export function clearAuth() {
  localStorage.removeItem(AUTH_KEY);
  window.dispatchEvent(new Event("bank-arch:auth"));
}

export function useAuth(): { user: AuthUser | null } {
  const [user, setUser] = useState<AuthUser | null>(() => loadAuth());
  useEffect(() => {
    const update = () => setUser(loadAuth());
    window.addEventListener("bank-arch:auth", update);
    window.addEventListener("storage", update);
    return () => {
      window.removeEventListener("bank-arch:auth", update);
      window.removeEventListener("storage", update);
    };
  }, []);
  return { user };
}
