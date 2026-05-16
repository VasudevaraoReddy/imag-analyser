import clsx from "clsx";
import { AlertOctagon, AlertTriangle, CheckCircle2, Info, MinusCircle } from "lucide-react";
import type { ReactNode } from "react";

type Status = "pass" | "fail" | "warn" | "not_applicable";
type Severity = "info" | "low" | "medium" | "high" | "critical";

export function StatusPill({
  status,
  children,
  size = "sm",
}: {
  status: Status;
  children: ReactNode;
  size?: "sm" | "md";
}) {
  const map: Record<Status, { cls: string; Icon: typeof CheckCircle2 }> = {
    pass: { cls: "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200", Icon: CheckCircle2 },
    fail: { cls: "bg-rose-50 text-rose-700 ring-1 ring-rose-200", Icon: AlertOctagon },
    warn: { cls: "bg-amber-50 text-amber-700 ring-1 ring-amber-200", Icon: AlertTriangle },
    not_applicable: { cls: "bg-slate-100 text-slate-600 ring-1 ring-slate-200", Icon: MinusCircle },
  };
  const { cls, Icon } = map[status];
  return (
    <span className={clsx(
      "inline-flex items-center gap-1 rounded-full font-medium",
      size === "sm" ? "px-2 py-0.5 text-xs" : "px-2.5 py-1 text-sm",
      cls,
    )}>
      <Icon className={size === "sm" ? "w-3 h-3" : "w-3.5 h-3.5"} />
      {children}
    </span>
  );
}

export function SeverityDot({ severity }: { severity: Severity }) {
  const colors: Record<Severity, string> = {
    critical: "bg-rose-600",
    high: "bg-rose-400",
    medium: "bg-amber-400",
    low: "bg-amber-300",
    info: "bg-slate-300",
  };
  return <span className={clsx("inline-block w-2 h-2 rounded-full", colors[severity])} />;
}

export function ReviewStatePill({ state }: { state: string }) {
  const map: Record<string, { cls: string; label: string; Icon: typeof CheckCircle2 }> = {
    auto_review_recommended: {
      cls: "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200",
      label: "Auto-review recommended",
      Icon: CheckCircle2,
    },
    needs_human_review: {
      cls: "bg-amber-50 text-amber-700 ring-1 ring-amber-200",
      label: "Needs human review",
      Icon: AlertTriangle,
    },
    rejected: {
      cls: "bg-rose-50 text-rose-700 ring-1 ring-rose-200",
      label: "Rejected",
      Icon: AlertOctagon,
    },
  };
  const m = map[state] ?? { cls: "bg-slate-100 text-slate-700", label: state, Icon: Info };
  return (
    <span className={clsx("pill", m.cls)}>
      <m.Icon className="w-3.5 h-3.5" /> {m.label}
    </span>
  );
}
