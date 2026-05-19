import { NavLink } from "react-router-dom";
import clsx from "clsx";
import { FilePlus2, Library, MessageSquare, ScrollText, Sparkles } from "lucide-react";
import { useAuth } from "../lib/auth";

type Item = {
  to: string;
  label: string;
  caption: string;
  Icon: typeof FilePlus2;
  adminOnly?: boolean;
};

const ITEMS: Item[] = [
  {
    to: "/",
    label: "New Arc Review",
    caption: "Upload a diagram",
    Icon: FilePlus2,
  },
  {
    to: "/reviews",
    label: "Arc Reviews",
    caption: "Past analyses",
    Icon: Library,
  },
  {
    to: "/chat",
    label: "Chat Bot",
    caption: "Ask about an architecture",
    Icon: MessageSquare,
  },
  {
    to: "/admin/usage",
    label: "AI Usage",
    caption: "Tokens, cost, model",
    Icon: Sparkles,
    adminOnly: true,
  },
  {
    to: "/admin/logs",
    label: "System logs",
    caption: "Platform-admin only",
    Icon: ScrollText,
    adminOnly: true,
  },
];

export function Sidebar() {
  const { user } = useAuth();
  const items = ITEMS.filter((i) => !i.adminOnly || user?.is_admin);

  return (
    <aside className="w-64 shrink-0 bg-white border-r border-slate-200 flex flex-col no-print h-full overflow-y-auto">
      <div className="px-3 py-3 text-[10px] uppercase tracking-[0.18em] text-slate-500 font-semibold">
        Workspace
      </div>
      <nav className="flex-1 px-2 space-y-1">
        {items.map(({ to, label, caption, Icon, adminOnly }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            className={({ isActive }) =>
              clsx(
                "group flex items-start gap-3 px-3 py-2.5 rounded-lg text-sm transition",
                isActive
                  ? "bg-brand-50 text-brand-700 ring-1 ring-brand-100"
                  : "text-slate-700 hover:bg-slate-50",
              )
            }
          >
            {({ isActive }) => (
              <>
                <Icon
                  className={clsx(
                    "w-4 h-4 mt-0.5 shrink-0",
                    isActive ? "text-brand" : "text-slate-400 group-hover:text-slate-600",
                  )}
                />
                <div className="leading-tight">
                  <div className="font-medium inline-flex items-center gap-1.5">
                    {label}
                    {adminOnly && (
                      <span className="text-[9px] uppercase tracking-wider bg-rose-100 text-rose-700 px-1 py-px rounded font-bold">
                        Admin
                      </span>
                    )}
                  </div>
                  <div className={clsx(
                    "text-[11px]",
                    isActive ? "text-brand-600" : "text-slate-500",
                  )}>{caption}</div>
                </div>
              </>
            )}
          </NavLink>
        ))}
      </nav>
      <div className="px-4 py-3 border-t border-slate-100 text-[11px] text-slate-400">
        YES BANK · Internal MVP
      </div>
    </aside>
  );
}
