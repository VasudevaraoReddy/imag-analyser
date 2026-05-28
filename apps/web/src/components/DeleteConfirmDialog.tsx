/**
 * DeleteConfirmDialog — modal that asks the admin to confirm a hard-delete.
 *
 * Props:
 *   open          – whether to show the dialog
 *   onClose       – called when the user dismisses without confirming
 *   onConfirm     – called when the user clicks "Permanently delete"
 *   arcNumber     – human-readable label (ARC-202605-009) shown in the title
 *   title         – analysis title / filename (shown as subtitle)
 *   isDeleting    – shows a spinner while the mutation is in flight
 *   result        – optional response from a successful delete (shows summary)
 *   error         – optional error message to surface inside the dialog
 */

import { useEffect, useRef } from "react";
import { AlertTriangle, Trash2, X, Loader2 } from "lucide-react";
import type { DeleteReviewResponse } from "../lib/api";

interface Props {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  arcNumber?: string;
  title?: string;
  isDeleting?: boolean;
  result?: DeleteReviewResponse | null;
  error?: string | null;
}

export function DeleteConfirmDialog({
  open,
  onClose,
  onConfirm,
  arcNumber,
  title,
  isDeleting = false,
  result = null,
  error = null,
}: Props) {
  const cancelRef = useRef<HTMLButtonElement>(null);

  // Trap focus to cancel button when dialog opens
  useEffect(() => {
    if (open && !result) {
      setTimeout(() => cancelRef.current?.focus(), 50);
    }
  }, [open, result]);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !isDeleting) onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, isDeleting, onClose]);

  if (!open) return null;

  const removedCount = result
    ? Object.values(result.artifacts).filter(Boolean).length
    : 0;
  const ledgerTotal = result
    ? (result.ledger_rows_purged.per_finding ?? 0) +
      (result.ledger_rows_purged.whole_review ?? 0)
    : 0;

  return (
    /* Backdrop */
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4"
      onClick={(e) => {
        if (e.target === e.currentTarget && !isDeleting) onClose();
      }}
      role="dialog"
      aria-modal="true"
      aria-labelledby="delete-dialog-title"
    >
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-md overflow-hidden">
        {/* Success state */}
        {result ? (
          <div className="p-6 space-y-4">
            <div className="flex items-center gap-3">
              <span className="w-10 h-10 rounded-full bg-emerald-100 flex items-center justify-center shrink-0">
                <Trash2 className="w-5 h-5 text-emerald-600" />
              </span>
              <div>
                <p className="font-semibold text-slate-900">Analysis deleted</p>
                <p className="text-sm text-slate-500">
                  {arcNumber || result.diagram_id}
                </p>
              </div>
            </div>
            <div className="rounded-lg bg-slate-50 p-3 text-sm space-y-1 text-slate-700">
              <div className="flex justify-between">
                <span>Files removed</span>
                <span className="font-medium tabular-nums">{removedCount}</span>
              </div>
              {ledgerTotal > 0 && (
                <div className="flex justify-between">
                  <span>Training rows purged</span>
                  <span className="font-medium tabular-nums">{ledgerTotal}</span>
                </div>
              )}
              {result.ledger_rows_purged.per_finding > 0 && (
                <div className="flex justify-between text-xs text-slate-500 pl-2">
                  <span>— per-finding decisions</span>
                  <span>{result.ledger_rows_purged.per_finding}</span>
                </div>
              )}
              {result.ledger_rows_purged.whole_review > 0 && (
                <div className="flex justify-between text-xs text-slate-500 pl-2">
                  <span>— whole-review labels</span>
                  <span>{result.ledger_rows_purged.whole_review}</span>
                </div>
              )}
            </div>
            <button
              onClick={onClose}
              className="w-full btn-primary justify-center"
            >
              Done
            </button>
          </div>
        ) : (
          <>
            {/* Header */}
            <div className="flex items-start justify-between p-5 border-b border-slate-100">
              <div className="flex items-center gap-3">
                <span className="w-10 h-10 rounded-full bg-rose-100 flex items-center justify-center shrink-0">
                  <AlertTriangle className="w-5 h-5 text-rose-600" />
                </span>
                <div>
                  <h2
                    id="delete-dialog-title"
                    className="font-semibold text-slate-900"
                  >
                    Delete{arcNumber ? ` ${arcNumber}` : " analysis"}?
                  </h2>
                  {title && (
                    <p className="text-sm text-slate-500 truncate max-w-[260px]">
                      {title}
                    </p>
                  )}
                </div>
              </div>
              <button
                onClick={onClose}
                disabled={isDeleting}
                className="text-slate-400 hover:text-slate-600 disabled:opacity-40"
                aria-label="Close"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Body */}
            <div className="p-5 space-y-4">
              <p className="text-sm text-slate-700 leading-relaxed">
                This will <span className="font-semibold text-rose-700">permanently</span> remove:
              </p>
              <ul className="text-sm text-slate-600 space-y-1.5 pl-4 list-disc">
                <li>The analysis JSON and all extracted data</li>
                <li>The original uploaded diagram image</li>
                <li>The processed / annotated image and OCR cache</li>
                <li>All per-finding and whole-review training labels</li>
              </ul>
              <p className="text-xs text-slate-500 bg-rose-50 border border-rose-100 rounded-lg px-3 py-2">
                This action <span className="font-semibold">cannot be undone</span>. Make sure
                you no longer need this review for training or compliance.
              </p>

              {error && (
                <div className="rounded-lg bg-rose-50 border border-rose-200 px-3 py-2 text-sm text-rose-700">
                  {error}
                </div>
              )}
            </div>

            {/* Footer */}
            <div className="flex justify-end gap-2 px-5 pb-5">
              <button
                ref={cancelRef}
                onClick={onClose}
                disabled={isDeleting}
                className="btn-secondary disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={onConfirm}
                disabled={isDeleting}
                className="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-medium rounded-lg bg-rose-600 text-white hover:bg-rose-700 disabled:opacity-60 disabled:cursor-not-allowed transition-colors"
              >
                {isDeleting ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Deleting…
                  </>
                ) : (
                  <>
                    <Trash2 className="w-4 h-4" />
                    Permanently delete
                  </>
                )}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
