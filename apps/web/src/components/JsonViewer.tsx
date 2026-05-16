export function JsonViewer({ value }: { value: unknown }) {
  return (
    <pre className="text-xs bg-slate-900 text-slate-100 rounded p-3 overflow-auto max-h-[600px]">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}
