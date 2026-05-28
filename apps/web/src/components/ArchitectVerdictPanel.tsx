/**
 * Architect's final Approve / Reject for the WHOLE review.
 *
 * Sits at the top of ResultsPage so the architect always sees the
 * current verdict — and once decided, the call goes into the training
 * ledger (data/feedback/reviews-YYYY-MM.jsonl) on the server.
 *
 * This is intentionally separate from the per-finding decisions in
 * CriticReviewTab: that one feeds *micro* training signal (which
 * fixes the model should suggest), this one feeds *macro* training
 * signal (does the entire extraction pass review?).
 */
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import {
  AlertTriangle,
  CheckCircle2,
  Gavel,
  Loader2,
  RefreshCw,
  ThumbsDown,
  ThumbsUp,
  XCircle,
} from "lucide-react";

import type { AnalysisResult } from "../types";
import { requestReReview, submitReviewDecision } from "../lib/api";

export function ArchitectVerdictPanel({ result }: { result: AnalysisResult }) {
  const qc = useQueryClient();
  const verdict = result.architect_decision;
  const decided = !!verdict;
  const candidatePending = !!result.candidate;

  const [pending, setPending] = useState<"approved" | "rejected" | null>(null);
  const [comment, setComment] = useState("");
  const [showCommentFor, setShowCommentFor] = useState<
    "approved" | "rejected" | null
  >(null);
  const [error, setError] = useState<string | null>(null);

  // Re-review state — separate from the Approve/Reject comment flow.
  const [showReReview, setShowReReview] = useState(false);
  const [reFeedback, setReFeedback] = useState("");
  const [reError, setReError] = useState<string | null>(null);
  const reReviewMut = useMutation({
    mutationFn: async (fb: string) => requestReReview(result.diagram_id, fb),
    onSuccess: (updated) => {
      qc.setQueryData(["analysis", result.diagram_id], updated);
      qc.invalidateQueries({ queryKey: ["analyses"] });
      setShowReReview(false);
      setReFeedback("");
    },
    onError: (e: Error) =>
      setReError(e.message || "Could not run re-review"),
  });

  const submitReReview = () => {
    setReError(null);
    if (reFeedback.trim().length < 5) {
      setReError("Please describe what to fix (at least a few words).");
      return;
    }
    reReviewMut.mutate(reFeedback.trim());
  };

  const mut = useMutation({
    mutationFn: async (v: { decision: "approved" | "rejected"; comment: string }) =>
      submitReviewDecision(result.diagram_id, v.decision, v.comment),
    onSuccess: (updated) => {
      qc.setQueryData(["analysis", result.diagram_id], updated);
      qc.invalidateQueries({ queryKey: ["analyses"] });
      setShowCommentFor(null);
      setComment("");
    },
  });

  const startDecision = (d: "approved" | "rejected") => {
    setError(null);
    setShowCommentFor(d);
  };

  const confirm = async () => {
    if (!showCommentFor) return;
    setPending(showCommentFor);
    try {
      await mut.mutateAsync({ decision: showCommentFor, comment });
    } catch (e) {
      setError((e as Error).message || "Could not save decision");
    } finally {
      setPending(null);
    }
  };

  // ─── Already decided ─────────────────────────────────────────────
  if (decided) {
    const isApproved = verdict.status === "approved";
    return (
      <div
        className={clsx(
          "card p-4 border-l-4",
          isApproved ? "border-emerald-500" : "border-rose-500",
        )}
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex items-start gap-3 min-w-0">
            <div
              className={clsx(
                "rounded-md p-2 shrink-0",
                isApproved
                  ? "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200"
                  : "bg-rose-50 text-rose-700 ring-1 ring-rose-200",
              )}
            >
              {isApproved ? (
                <CheckCircle2 className="w-5 h-5" />
              ) : (
                <XCircle className="w-5 h-5" />
              )}
            </div>
            <div className="min-w-0">
              <div className="text-xs uppercase tracking-wider text-slate-500 font-semibold">
                Architect verdict
              </div>
              <div className="text-base font-semibold text-slate-900 mt-0.5">
                {isApproved ? "Approved" : "Rejected"}
              </div>
              <div className="text-xs text-slate-500 mt-0.5">
                {verdict.decided_by_name || verdict.decided_by_employee_id || "—"}
                {verdict.decided_by_role && (
                  <span className="ml-1 text-slate-400">
                    · {verdict.decided_by_role}
                  </span>
                )}
                {" · "}
                {new Date(verdict.decided_at).toLocaleString()}
              </div>
              {verdict.comment && (
                <div className="mt-2 text-sm text-slate-700 bg-white ring-1 ring-slate-200 rounded-md px-3 py-2 max-w-2xl">
                  <span className="text-slate-400 text-[11px] uppercase tracking-wider mr-1">
                    Note:
                  </span>
                  {verdict.comment}
                </div>
              )}
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              className="btn-secondary text-xs"
              onClick={() => {
                setShowReReview(true);
                setShowCommentFor(null);
              }}
              disabled={mut.isPending || candidatePending}
              title={
                candidatePending
                  ? "A candidate re-review is already pending"
                  : "Ask the AI to re-extract with your feedback"
              }
            >
              <RefreshCw className="w-3.5 h-3.5" />
              Request re-review
            </button>
            <button
              className="btn-secondary text-xs"
              onClick={() => setShowCommentFor(isApproved ? "rejected" : "approved")}
              disabled={mut.isPending || candidatePending}
              title="Change the architect's verdict"
            >
              Change verdict
            </button>
          </div>
        </div>

        {showCommentFor && (
          <ChangeVerdictForm
            target={showCommentFor}
            comment={comment}
            setComment={setComment}
            confirm={confirm}
            pending={pending}
            cancel={() => {
              setShowCommentFor(null);
              setComment("");
              setError(null);
            }}
            error={error}
          />
        )}
        {showReReview && (
          <ReReviewForm
            feedback={reFeedback}
            setFeedback={setReFeedback}
            submit={submitReReview}
            cancel={() => {
              setShowReReview(false);
              setReFeedback("");
              setReError(null);
            }}
            pending={reReviewMut.isPending}
            error={reError}
          />
        )}
      </div>
    );
  }

  // ─── Not yet decided ─────────────────────────────────────────────
  return (
    <div className="card p-4 border-l-4 border-amber-400">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3 min-w-0">
          <div className="rounded-md p-2 bg-amber-50 text-amber-700 ring-1 ring-amber-200 shrink-0">
            <Gavel className="w-5 h-5" />
          </div>
          <div className="min-w-0">
            <div className="text-xs uppercase tracking-wider text-slate-500 font-semibold">
              Architect verdict
            </div>
            <div className="text-base font-semibold text-slate-900 mt-0.5">
              Awaiting your review
            </div>
            <div className="text-xs text-slate-600 mt-0.5 max-w-xl">
              Approve or Reject the entire analysis. Your decision is saved
              to the training ledger so future model versions get better at
              reviews like this one.
            </div>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            className="btn-primary"
            onClick={() => startDecision("approved")}
            disabled={mut.isPending || candidatePending}
          >
            <ThumbsUp className="w-4 h-4" /> Approve review
          </button>
          <button
            className="btn-secondary"
            onClick={() => startDecision("rejected")}
            disabled={mut.isPending || candidatePending}
          >
            <ThumbsDown className="w-4 h-4" /> Reject review
          </button>
          <button
            className="btn-secondary"
            onClick={() => {
              setShowReReview(true);
              setShowCommentFor(null);
            }}
            disabled={mut.isPending || reReviewMut.isPending || candidatePending}
            title={
              candidatePending
                ? "A candidate re-review is already pending"
                : "Ask the AI to re-extract with your feedback"
            }
          >
            <RefreshCw className="w-4 h-4" /> Request re-review
          </button>
        </div>
      </div>

      {showCommentFor && (
        <ChangeVerdictForm
          target={showCommentFor}
          comment={comment}
          setComment={setComment}
          confirm={confirm}
          pending={pending}
          cancel={() => {
            setShowCommentFor(null);
            setComment("");
            setError(null);
          }}
          error={error}
        />
      )}

      {showReReview && (
        <ReReviewForm
          feedback={reFeedback}
          setFeedback={setReFeedback}
          submit={submitReReview}
          cancel={() => {
            setShowReReview(false);
            setReFeedback("");
            setReError(null);
          }}
          pending={reReviewMut.isPending}
          error={reError}
        />
      )}
    </div>
  );
}


function ReReviewForm({
  feedback,
  setFeedback,
  submit,
  cancel,
  pending,
  error,
}: {
  feedback: string;
  setFeedback: (v: string) => void;
  submit: () => void;
  cancel: () => void;
  pending: boolean;
  error: string | null;
}) {
  return (
    <div className="mt-3 rounded-md border border-amber-200 bg-amber-50/50 p-3">
      <div className="text-sm font-medium text-slate-800 mb-1.5">
        Tell the AI what to fix
      </div>
      <div className="text-xs text-slate-600 mb-2">
        <span className="italic">"You missed the WAF in front of App tier"</span>,{" "}
        <span className="italic">"Journey 2 has the arrow flipped"</span>,{" "}
        <span className="italic">"Front Door label is misspelled"</span>.
      </div>
      <textarea
        className="w-full text-sm rounded-md border border-slate-300 focus:border-brand focus:ring-1 focus:ring-brand px-3 py-2 min-h-[80px]"
        placeholder="What did the AI get wrong?"
        value={feedback}
        onChange={(e) => setFeedback(e.target.value)}
        disabled={pending}
      />
      {error && (
        <div className="text-xs text-rose-600 mt-1.5 inline-flex items-center gap-1">
          <AlertTriangle className="w-3.5 h-3.5" /> {error}
        </div>
      )}
      {pending && (
        <div className="text-xs text-slate-600 mt-2 inline-flex items-center gap-1.5">
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
          Re-analyzing with your feedback (this can take a minute)…
        </div>
      )}
      <div className="flex justify-end gap-2 mt-2">
        <button
          className="btn-secondary text-xs"
          onClick={cancel}
          disabled={pending}
        >
          Cancel
        </button>
        <button
          className="text-xs btn-primary !bg-amber-600 hover:!bg-amber-700"
          onClick={submit}
          disabled={pending}
        >
          {pending ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <RefreshCw className="w-3.5 h-3.5" />
          )}
          Run re-review
        </button>
      </div>
    </div>
  );
}


function ChangeVerdictForm({
  target,
  comment,
  setComment,
  confirm,
  cancel,
  pending,
  error,
}: {
  target: "approved" | "rejected";
  comment: string;
  setComment: (v: string) => void;
  confirm: () => void;
  cancel: () => void;
  pending: "approved" | "rejected" | null;
  error: string | null;
}) {
  const isApprove = target === "approved";
  return (
    <div className="mt-3 rounded-md border border-slate-200 bg-slate-50/60 p-3">
      <div className="text-sm font-medium text-slate-800 mb-1.5">
        {isApprove ? "Approve this review" : "Reject this review"}
      </div>
      <div className="text-xs text-slate-500 mb-2">
        {isApprove
          ? "Optional: add any context for the training dataset (e.g. \"compliant after WAF retrofit\")."
          : "Tell us what's wrong — this is the most valuable training signal we get."}
      </div>
      <textarea
        className="w-full text-sm rounded-md border border-slate-300 focus:border-brand focus:ring-1 focus:ring-brand px-3 py-2 min-h-[64px]"
        placeholder={
          isApprove
            ? "Looks correct. (optional)"
            : "What did the AI get wrong?"
        }
        value={comment}
        onChange={(e) => setComment(e.target.value)}
        disabled={!!pending}
      />
      {error && (
        <div className="text-xs text-rose-600 mt-1.5 inline-flex items-center gap-1">
          <AlertTriangle className="w-3.5 h-3.5" /> {error}
        </div>
      )}
      <div className="flex justify-end gap-2 mt-2">
        <button className="btn-secondary text-xs" onClick={cancel} disabled={!!pending}>
          Cancel
        </button>
        <button
          className={clsx(
            "text-xs btn-primary",
            !isApprove && "!bg-rose-600 hover:!bg-rose-700",
          )}
          onClick={confirm}
          disabled={!!pending}
        >
          {pending ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          ) : isApprove ? (
            <ThumbsUp className="w-3.5 h-3.5" />
          ) : (
            <ThumbsDown className="w-3.5 h-3.5" />
          )}
          Confirm {isApprove ? "Approve" : "Reject"}
        </button>
      </div>
    </div>
  );
}
