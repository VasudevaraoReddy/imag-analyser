import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import clsx from "clsx";
import { Bot, Loader2, Send, Sparkles, User } from "lucide-react";
import { listAnalyses, sendChat, type ChatMessage } from "../lib/api";

const STARTERS = [
  "Give me a summary of this analysis.",
  "Show the compliance findings.",
  "How many north-south flows are there?",
  "Which trust zones are present?",
  "What components are in the data tier?",
];

export default function ChatPage() {
  const [params, setParams] = useSearchParams();
  const initialAnalysisId = params.get("analysis_id");

  const [analysisId, setAnalysisId] = useState<string | null>(initialAnalysisId);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const { data: analyses } = useQuery({
    queryKey: ["history"],
    queryFn: listAnalyses,
  });

  const selected = useMemo(
    () => analyses?.find((a) => a.diagram_id === analysisId) ?? null,
    [analyses, analysisId],
  );

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, sending]);

  useEffect(() => {
    if (analysisId) params.set("analysis_id", analysisId);
    else params.delete("analysis_id");
    setParams(params, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analysisId]);

  const handleSend = async (textOverride?: string) => {
    const text = (textOverride ?? input).trim();
    if (!text || sending) return;
    setError(null);
    const next: ChatMessage[] = [...messages, { role: "user", content: text }];
    setMessages(next);
    setInput("");
    setSending(true);
    try {
      const res = await sendChat(next, analysisId);
      setMessages([...next, { role: "assistant", content: res.reply }]);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="h-full flex">
      {/* Context picker */}
      <aside className="w-72 shrink-0 border-r border-slate-200 bg-white p-4 space-y-3 overflow-auto">
        <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500 font-semibold">
          Conversation context
        </div>
        <select
          value={analysisId ?? ""}
          onChange={(e) => {
            setAnalysisId(e.target.value || null);
            setMessages([]);
          }}
          className="w-full text-sm border border-slate-200 rounded-md px-2 py-2 focus:outline-none focus:ring-2 focus:ring-brand/30"
        >
          <option value="">None — general questions</option>
          {(analyses ?? []).map((a) => (
            <option key={a.diagram_id} value={a.diagram_id}>
              {a.arc_number ? `${a.arc_number} — ` : ""}{a.title || a.filename}
            </option>
          ))}
        </select>
        {selected && (
          <div className="text-xs text-slate-600 space-y-1 border border-slate-100 rounded-md p-3 bg-slate-50">
            {selected.arc_number && (
              <div className="font-mono text-brand-700 text-[11px]">{selected.arc_number}</div>
            )}
            <div className="font-medium text-slate-800">{selected.title || selected.filename}</div>
            {selected.title && (
              <div className="text-[11px] text-slate-500">{selected.filename}</div>
            )}
            <div className="pt-1 border-t border-slate-200/70 mt-1">Provider: {selected.primary_provider}</div>
            <div>Components: {selected.components_count}</div>
            <div>Confidence: {Math.round(selected.overall_confidence * 100)}%</div>
            <div>State: {selected.review_state}</div>
          </div>
        )}
        <div className="pt-3">
          <div className="text-[10px] uppercase tracking-[0.18em] text-slate-500 font-semibold mb-2">
            Quick prompts
          </div>
          <div className="space-y-1.5">
            {STARTERS.map((s) => (
              <button
                key={s}
                onClick={() => handleSend(s)}
                disabled={sending}
                className="w-full text-left text-xs px-2 py-1.5 rounded-md border border-slate-200 hover:bg-brand-50 hover:border-brand-200 transition disabled:opacity-50"
              >
                <Sparkles className="inline w-3 h-3 mr-1 text-brand" /> {s}
              </button>
            ))}
          </div>
        </div>
      </aside>

      {/* Chat thread */}
      <section className="flex-1 min-w-0 flex flex-col bg-slate-50">
        <header className="px-6 py-3 border-b border-slate-200 bg-white flex items-center gap-2">
          <Bot className="w-5 h-5 text-brand" />
          <div className="leading-tight">
            <div className="font-semibold text-slate-900">Architecture Chat Bot</div>
            <div className="text-xs text-slate-500">
              {selected
                ? `Discussing: ${selected.filename}`
                : "No analysis selected — ask general questions"}
            </div>
          </div>
        </header>

        <div ref={scrollRef} className="flex-1 overflow-auto px-6 py-6 space-y-4">
          {messages.length === 0 && (
            <div className="max-w-2xl mx-auto text-center text-slate-500 pt-10">
              <Bot className="w-10 h-10 text-brand mx-auto mb-3" />
              <div className="font-medium text-slate-700">Ask anything about the architecture.</div>
              <div className="text-sm mt-1">
                Pick a past Arc Review on the left to ground the conversation in its findings,
                or just type a question.
              </div>
            </div>
          )}
          {messages.map((m, i) => (
            <Message key={i} message={m} />
          ))}
          {sending && (
            <div className="flex items-center gap-2 text-slate-500 text-sm">
              <Loader2 className="w-4 h-4 animate-spin text-brand" /> Thinking…
            </div>
          )}
          {error && (
            <div className="bg-rose-50 border border-rose-200 text-rose-700 rounded-md p-3 text-sm">
              {error}
            </div>
          )}
        </div>

        <footer className="border-t border-slate-200 bg-white p-3">
          <div className="max-w-4xl mx-auto flex gap-2">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSend();
                }
              }}
              rows={1}
              placeholder="Ask about components, flows, compliance… (Enter to send)"
              className="flex-1 resize-none rounded-md border border-slate-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand/30 focus:border-brand min-h-[40px] max-h-32"
            />
            <button
              onClick={() => handleSend()}
              disabled={sending || !input.trim()}
              className="btn-primary disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Send className="w-4 h-4" /> Send
            </button>
          </div>
        </footer>
      </section>
    </div>
  );
}

function Message({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  return (
    <div className={clsx("flex gap-3", isUser ? "justify-end" : "justify-start")}>
      {!isUser && (
        <div className="w-8 h-8 rounded-full bg-brand-50 ring-1 ring-brand-100 flex items-center justify-center shrink-0">
          <Bot className="w-4 h-4 text-brand" />
        </div>
      )}
      <div
        className={clsx(
          "max-w-2xl rounded-lg px-3.5 py-2.5 text-sm whitespace-pre-wrap leading-relaxed",
          isUser
            ? "bg-brand text-white"
            : "bg-white text-slate-800 border border-slate-200 shadow-card",
        )}
      >
        {message.content}
      </div>
      {isUser && (
        <div className="w-8 h-8 rounded-full bg-slate-200 flex items-center justify-center shrink-0">
          <User className="w-4 h-4 text-slate-600" />
        </div>
      )}
    </div>
  );
}
