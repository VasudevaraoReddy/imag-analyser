import clsx from "clsx";

export function ConfidenceBadge({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color =
    value >= 0.85 ? "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200" :
    value >= 0.6 ? "bg-amber-50 text-amber-700 ring-1 ring-amber-200" :
    "bg-rose-50 text-rose-700 ring-1 ring-rose-200";
  return (
    <span className={clsx("pill", color)}>
      <span className="inline-block w-1.5 h-1.5 rounded-full bg-current opacity-70" />
      {pct}% confidence
    </span>
  );
}
