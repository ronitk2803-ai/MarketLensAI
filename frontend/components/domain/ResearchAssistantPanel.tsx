"use client";

import { Loader2, Send } from "lucide-react";
import { useState } from "react";

import { Panel } from "@/components/terminal/Panel";

/**
 * NL Research Assistant — one question per request, not a persisted chat
 * thread (Build_plan.md §S step 25 is scoped to single-question research;
 * see app/services/research_assistant.py's module docstring). This
 * component keeps a local, in-memory list of past Q&A pairs purely for
 * the reader's own scrollback within one page visit — nothing here is
 * saved server-side, and reloading the page starts fresh.
 */

const EXAMPLE_QUESTIONS = [
  "Has RELIANCE fallen this much before, and did it recover?",
  "Compare TCS with its industry peers.",
  "Find companies with unusual trading volume recently.",
  "Summarize my portfolio.",
];

interface Turn {
  question: string;
  answer?: string;
  toolsUsed?: string[];
  error?: string;
}

export function ResearchAssistantPanel() {
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [loading, setLoading] = useState(false);

  async function submit(q: string) {
    const trimmed = q.trim();
    if (!trimmed || loading) return;
    setLoading(true);
    setQuestion("");
    const index = turns.length;
    setTurns((prev) => [...prev, { question: trimmed }]);

    try {
      const res = await fetch("/api/assistant/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: trimmed }),
      });
      const body = await res.json();
      setTurns((prev) => {
        const next = [...prev];
        if (!res.ok) {
          next[index] = {
            ...next[index],
            error: body.error ?? "Couldn't get an answer — try again in a moment.",
          };
        } else {
          next[index] = { ...next[index], answer: body.answer, toolsUsed: body.tools_used };
        }
        return next;
      });
    } catch {
      setTurns((prev) => {
        const next = [...prev];
        next[index] = { ...next[index], error: "Couldn't reach the assistant — try again." };
        return next;
      });
    } finally {
      setLoading(false);
    }
  }

  return (
    <Panel
      title="Research assistant"
      footnote="AI-generated answers, grounded only in this app's own stored data — never a general-knowledge guess. Produced for research and analytical purposes only, not investment advice. MarketLens AI is not a SEBI-registered investment adviser or research analyst."
    >
      <div className="flex flex-col gap-4 px-1 py-2">
        {turns.length === 0 ? (
          <div className="flex flex-col gap-2 px-2 py-4">
            <p className="text-xs text-muted-foreground">
              Ask a research question in plain language — the assistant looks up real data
              (scores, technicals, history, news, your portfolio) before answering, and says so
              when it can&rsquo;t find something rather than guessing.
            </p>
            <div className="flex flex-col gap-1.5">
              {EXAMPLE_QUESTIONS.map((q) => (
                <button
                  key={q}
                  type="button"
                  onClick={() => submit(q)}
                  disabled={loading}
                  className="w-fit rounded-md border border-border bg-surface-raised px-2.5 py-1 text-left text-xs text-muted-foreground hover:bg-accent/40 hover:text-foreground disabled:opacity-50"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            {turns.map((turn, i) => (
              <div key={i} className="flex flex-col gap-1.5 border-b border-border/60 pb-4 last:border-0">
                <p className="text-sm font-medium">{turn.question}</p>
                {turn.answer && (
                  <>
                    <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">
                      {turn.answer}
                    </p>
                    {turn.toolsUsed && turn.toolsUsed.length > 0 && (
                      <p className="text-[11px] text-muted-foreground">
                        Looked up: {turn.toolsUsed.join(", ")}
                      </p>
                    )}
                  </>
                )}
                {turn.error && <p className="text-xs text-down">{turn.error}</p>}
                {!turn.answer && !turn.error && (
                  <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                    <Loader2 className="size-3 animate-spin" aria-hidden />
                    Looking into it…
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        <form
          onSubmit={(e) => {
            e.preventDefault();
            submit(question);
          }}
          className="flex items-end gap-2"
        >
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit(question);
              }
            }}
            placeholder="Ask a research question…"
            rows={2}
            disabled={loading}
            className="min-w-0 flex-1 resize-none rounded-md border border-border bg-surface-raised px-2.5 py-1.5 text-sm outline-none focus:border-primary disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={loading || !question.trim()}
            className="inline-flex items-center gap-1.5 self-stretch rounded-md border border-border bg-surface-raised px-3 text-xs font-medium hover:bg-surface-raised/70 disabled:opacity-50"
          >
            {loading ? (
              <Loader2 className="size-3.5 animate-spin" aria-hidden />
            ) : (
              <Send className="size-3.5" aria-hidden />
            )}
            Ask
          </button>
        </form>
      </div>
    </Panel>
  );
}
