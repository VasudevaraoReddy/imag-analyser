import { useEffect, useState } from "react";

// MVP client-side auth state. The actual credential check happens on the
// backend (POST /api/auth/login). The shape below is what we cache locally
// for header display and to gate routes.
// TODO: replace with Entra ID / OAuth before non-localhost deployment.
const AUTH_KEY = "bank-arch.auth.user";

export type AuthUser = {
  employee_id: string;
  name: string;
  role: string;
  email: string;
  is_admin: boolean;
  token: string;
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

// Cross-component signal that an API call returned 401 because the
// architect's session expired (token TTL hit on the server). RequireAuth
// listens for this and routes to /login with a banner. We use
// sessionStorage so a hard reload still shows the banner once.
const SESSION_EXPIRED_KEY = "bank-arch.session-expired";

export function markSessionExpired() {
  try {
    sessionStorage.setItem(SESSION_EXPIRED_KEY, "1");
  } catch {
    /* sessionStorage can be blocked in some embedded browsers */
  }
  clearAuth();
  window.dispatchEvent(new Event("bank-arch:session-expired"));
}

export function consumeSessionExpiredFlag(): boolean {
  try {
    const flag = sessionStorage.getItem(SESSION_EXPIRED_KEY);
    if (flag) {
      sessionStorage.removeItem(SESSION_EXPIRED_KEY);
      return true;
    }
  } catch {
    /* ignore */
  }
  return false;
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
