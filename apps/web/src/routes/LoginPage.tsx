import { useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { Eye, EyeOff, Loader2, LogIn, ShieldCheck } from "lucide-react";
import { saveAuth } from "../lib/auth";
import { login } from "../lib/api";
import { YES_BANK_BLUE, YES_BANK_RED, YES_BANK_LOGO } from "../lib/brand";

export default function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from ?? "/";

  const [employeeId, setEmployeeId] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!employeeId.trim() || !password) {
      setError("Employee ID and password are required.");
      return;
    }
    setSubmitting(true);
    try {
      const user = await login(employeeId.trim(), password);
      saveAuth({
        employee_id: user.employee_id,
        name: user.name,
        role: user.role,
        email: user.email,
        token: user.token,
        signed_in_at: new Date().toISOString(),
      });
      navigate(from, { replace: true });
    } catch (err) {
      const msg = (err as Error).message || "Sign-in failed.";
      // Strip the "API 401:" prefix from jsonFetch so users see a clean message
      const clean = msg.replace(/^API \d+:\s*/, "").replace(/[{}"]/g, "").trim();
      setError(
        /invalid|401/i.test(msg)
          ? "Invalid employee ID or password."
          : clean || "Sign-in failed.",
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="h-screen w-screen flex overflow-hidden bg-slate-50">
      {/* Left brand panel */}
      <aside
        className="hidden md:flex flex-1 flex-col justify-between text-white relative"
        style={{ backgroundColor: '#00518F' }}
      >
        <div className="h-1 w-full" style={{ backgroundColor: YES_BANK_RED }} />
        <div className="absolute inset-0 opacity-[0.08] pointer-events-none">
          <svg className="w-full h-full" viewBox="0 0 800 600" preserveAspectRatio="xMidYMid slice">
            <defs>
              <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
                <path d="M 40 0 L 0 0 0 40" fill="none" stroke="white" strokeWidth="1" />
              </pattern>
            </defs>
            <rect width="100%" height="100%" fill="url(#grid)" />
          </svg>
        </div>

        <div className="relative z-10 p-10">
          <div className="flex items-center gap-3">
            <div className="bg-white rounded-md p-1.5 shadow-md">
              <img src={YES_BANK_LOGO} alt="YES BANK" className="h-10 w-auto" />
            </div>
            <div>
              <div className="text-[11px] uppercase tracking-[0.2em] text-white/75">YES BANK</div>
              <div className="text-sm font-medium">Internal Tools</div>
            </div>
          </div>
        </div>

        <div className="relative z-10 px-10 pb-12">
          <h1 className="text-4xl font-semibold tracking-tight leading-tight">
            Architecture<br />Diagram Analyzer
          </h1>
          <p className="mt-4 text-white/85 max-w-md leading-relaxed">
            Submit cloud architecture diagrams for automated component extraction,
            flow classification, and compliance review against the bank's reference controls.
          </p>
          <div className="mt-8 flex items-center gap-2 text-sm text-white/80">
            <ShieldCheck className="w-4 h-4" />
            Restricted to authorized employees · Internal use only
          </div>
        </div>

        <div className="relative z-10 px-10 py-4 text-[11px] text-white/55 border-t border-white/15">
          © YES BANK · For internal review purposes only
        </div>
      </aside>

      {/* Right login panel */}
      <main className="w-full md:w-[480px] shrink-0 flex items-center justify-center p-6 md:p-10 bg-white">
        <div className="w-full max-w-sm">
          {/* Mobile brand */}
          <div className="md:hidden flex items-center gap-3 mb-8">
            <div className="bg-white rounded-md p-1 shadow-sm ring-1 ring-slate-200">
              <img src={YES_BANK_LOGO} alt="YES BANK" className="h-8 w-auto" />
            </div>
            <div className="text-sm font-medium text-slate-900">YES BANK · Internal</div>
          </div>

          <div>
            <div className="text-xs uppercase tracking-[0.18em] text-brand font-semibold">
              Sign in
            </div>
            <h2 className="text-2xl font-semibold tracking-tight text-slate-900 mt-1">
              Welcome back
            </h2>
            <p className="text-sm text-slate-600 mt-1">
              Use your YES BANK employee ID to continue.
            </p>
          </div>

          <form onSubmit={handleSubmit} className="mt-7 space-y-4">
            <div>
              <label className="block text-sm font-medium text-slate-800">
                Employee ID
              </label>
              <input
                type="text"
                autoComplete="username"
                autoFocus
                required
                value={employeeId}
                onChange={(e) => setEmployeeId(e.target.value)}
                placeholder="e.g. YB123456"
                disabled={submitting}
                className="mt-1 w-full text-sm rounded-md border border-slate-300 px-3 py-2.5 focus:outline-none focus:ring-2 focus:ring-brand/30 focus:border-brand uppercase tracking-wide"
              />
            </div>

            <div>
              <div className="flex items-center justify-between">
                <label className="block text-sm font-medium text-slate-800">
                  Password
                </label>
                <button type="button" className="text-xs text-brand hover:underline">
                  Forgot password?
                </button>
              </div>
              <div className="relative mt-1">
                <input
                  type={showPassword ? "text" : "password"}
                  autoComplete="current-password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  disabled={submitting}
                  className="w-full text-sm rounded-md border border-slate-300 px-3 py-2.5 pr-10 focus:outline-none focus:ring-2 focus:ring-brand/30 focus:border-brand"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 text-slate-400 hover:text-slate-700"
                  aria-label={showPassword ? "Hide password" : "Show password"}
                >
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            {error && (
              <div className="text-sm text-rose-700 bg-rose-50 border border-rose-200 rounded-md px-3 py-2">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={submitting}
              className="btn-primary w-full justify-center py-2.5 text-base disabled:opacity-50"
            >
              {submitting ? (
                <><Loader2 className="w-4 h-4 animate-spin" /> Signing in…</>
              ) : (
                <><LogIn className="w-4 h-4" /> Sign in</>
              )}
            </button>

            <div className="text-[11px] text-slate-400 text-center pt-2">
              Single-Sign-On via Entra ID is coming soon.
              <br />
              By signing in you agree to YES BANK's internal acceptable-use policy.
            </div>
          </form>
        </div>
      </main>
    </div>
  );
}
