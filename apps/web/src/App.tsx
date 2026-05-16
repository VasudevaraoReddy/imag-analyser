import { Link, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { LayoutDashboard, Upload, FileText } from "lucide-react";
import UploadPage from "./routes/UploadPage";
import ResultsPage from "./routes/ResultsPage";
import HistoryPage from "./routes/HistoryPage";
import ReportPage from "./routes/ReportPage";

function Nav() {
  const linkBase =
    "flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-md transition";
  const linkActive = "bg-white/15 text-white font-medium";
  const linkIdle = "text-white/80 hover:text-white hover:bg-white/10";
  return (
    <nav className="flex items-center gap-1">
      <NavLink to="/" end className={({ isActive }) => `${linkBase} ${isActive ? linkActive : linkIdle}`}>
        <Upload className="w-4 h-4" /> Upload
      </NavLink>
      <NavLink to="/history" className={({ isActive }) => `${linkBase} ${isActive ? linkActive : linkIdle}`}>
        <LayoutDashboard className="w-4 h-4" /> History
      </NavLink>
    </nav>
  );
}

export default function App() {
  const location = useLocation();
  const isReport = location.pathname.endsWith("/report");
  return (
    <div className="min-h-screen flex flex-col bg-slate-50">
      {!isReport && (
        <header className="bg-brand text-white shadow-elev no-print">
          <div className="max-w-7xl mx-auto px-6 h-14 flex items-center justify-between">
            <Link to="/" className="flex items-center gap-2.5">
              <div className="w-7 h-7 rounded-md bg-white/15 flex items-center justify-center">
                <FileText className="w-4 h-4 text-white" />
              </div>
              <div className="leading-tight">
                <div className="text-base font-semibold tracking-tight">
                  Architecture Diagram Analyzer
                </div>
                <div className="text-[11px] text-white/70 uppercase tracking-wider">
                  Internal · Cloud Security Review
                </div>
              </div>
            </Link>
            <Nav />
          </div>
        </header>
      )}
      <main className="flex-1">
        <Routes>
          <Route path="/" element={<UploadPage />} />
          <Route path="/results/:id" element={<ResultsPage />} />
          <Route path="/results/:id/report" element={<ReportPage />} />
          <Route path="/history" element={<HistoryPage />} />
        </Routes>
      </main>
    </div>
  );
}
