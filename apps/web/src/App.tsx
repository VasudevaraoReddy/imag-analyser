import { Link, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { LogOut, UserRound } from "lucide-react";
import UploadPage from "./routes/UploadPage";
import ResultsPage from "./routes/ResultsPage";
import HistoryPage from "./routes/HistoryPage";
import ReportPage from "./routes/ReportPage";
import ChatPage from "./routes/ChatPage";
import LoginPage from "./routes/LoginPage";
import LogsPage from "./routes/LogsPage";
import UsagePage from "./routes/UsagePage";
import { Sidebar } from "./components/Sidebar";
import { clearAuth, useAuth } from "./lib/auth";
import { YES_BANK_BLUE, YES_BANK_RED, YES_BANK_LOGO } from "./lib/brand";

function RequireAuth({ children }: { children: JSX.Element }) {
  const { user } = useAuth();
  const location = useLocation();
  if (!user) {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  }
  return children;
}

function UserMenu() {
  const { user } = useAuth();
  if (!user) return null;
  return (
    <div className="flex items-center gap-3 text-sm">
      <div className="hidden sm:flex items-center gap-2 text-white/90">
        <div className="w-7 h-7 rounded-full bg-white/15 flex items-center justify-center">
          <UserRound className="w-4 h-4" />
        </div>
        <div className="leading-tight">
          <div className="font-medium">{user.name || user.employee_id}</div>
          <div className="text-[10px] uppercase tracking-wider text-white/70">
            {user.employee_id}{user.role ? ` · ${user.role}` : ""}
          </div>
        </div>
      </div>
      <button
        onClick={() => clearAuth()}
        className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-white/85 hover:bg-white/10 hover:text-white transition"
        title="Sign out"
      >
        <LogOut className="w-4 h-4" /> Sign out
      </button>
    </div>
  );
}

export default function App() {
  const location = useLocation();

  // Login is its own full-bleed page
  if (location.pathname === "/login") {
    return (
      <Routes>
        <Route path="/login" element={<LoginPage />} />
      </Routes>
    );
  }

  const isReport = location.pathname.endsWith("/report");

  if (isReport) {
    return (
      <Routes>
        <Route
          path="/results/:id/report"
          element={
            <RequireAuth>
              <ReportPage />
            </RequireAuth>
          }
        />
      </Routes>
    );
  }

  return (
    <RequireAuth>
      <div className="h-screen flex flex-col bg-slate-50 overflow-hidden">
        <header
          className="text-white shadow-elev no-print relative shrink-0"
          style={{ backgroundColor: YES_BANK_BLUE }}
        >
          <div className="h-1 w-full" style={{ backgroundColor: YES_BANK_RED }} />
          <div className="px-6 h-16 flex items-center justify-between">
            <Link to="/" className="flex items-center gap-3">
              <div className="bg-white rounded-md p-1 flex items-center justify-center shadow-sm">
                <img src={YES_BANK_LOGO} alt="YES BANK" className="h-8 w-auto" />
              </div>
              <div className="leading-tight border-l border-white/25 pl-3">
                <div className="text-base font-semibold tracking-tight">
                  Architecture Diagram Analyzer
                </div>
                <div className="text-[11px] text-white/80 uppercase tracking-[0.15em]">
                  Internal · Cloud Security Review
                </div>
              </div>
            </Link>
            <UserMenu />
          </div>
        </header>
        <div className="flex flex-1 min-h-0 overflow-hidden">
          <Sidebar />
          <main className="flex-1 min-w-0 min-h-0 overflow-y-auto overflow-x-hidden">
            <Routes>
              <Route path="/" element={<UploadPage />} />
              <Route path="/reviews" element={<HistoryPage />} />
              <Route path="/results/:id" element={<ResultsPage />} />
              <Route path="/chat" element={<ChatPage />} />
              <Route path="/history" element={<HistoryPage />} />
              <Route path="/admin/logs" element={<LogsPage />} />
              <Route path="/admin/usage" element={<UsagePage />} />
            </Routes>
          </main>
        </div>
      </div>
    </RequireAuth>
  );
}
