import clsx from "clsx";
import type { Provider } from "../types";

const colors: Record<string, string> = {
  azure: "bg-brand-50 text-brand-700 ring-1 ring-brand-200",
  aws: "bg-orange-50 text-orange-700 ring-1 ring-orange-200",
  gcp: "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200",
  oci: "bg-red-50 text-red-700 ring-1 ring-red-200",
  on_prem: "bg-slate-100 text-slate-700 ring-1 ring-slate-200",
  kubernetes: "bg-indigo-50 text-indigo-700 ring-1 ring-indigo-200",
  multi: "bg-violet-50 text-violet-700 ring-1 ring-violet-200",
  other: "bg-slate-50 text-slate-600 ring-1 ring-slate-200",
  unknown: "bg-slate-50 text-slate-500 ring-1 ring-slate-200",
};

export function ProviderBadge({ provider }: { provider: Provider | string }) {
  return (
    <span className={clsx("pill", colors[provider] || colors.other)}>
      {provider}
    </span>
  );
}
