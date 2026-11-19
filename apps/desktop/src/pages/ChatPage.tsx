import { useEffect, useMemo, useRef, useState } from "react";
import {
  Bot,
  MessageSquarePlus,
  MessagesSquare,
  Send,
  Sparkles,
  Trash2,
} from "lucide-react";

import { AiNotice } from "@/components/ui/AiNotice";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { DataRow } from "@/components/ui/DataRow";
import { GroupLabel } from "@/components/ui/Panel";
import { Spinner } from "@/components/ui/Spinner";
import { usePolling } from "@/hooks/usePolling";
import { ApiError, api } from "@/lib/api";
import {
  formatBrokerTime,
  formatPercent,
  formatPrice,
  formatTimeOnly,
} from "@/lib/format";
import type {
  ChatConversation,
  ChatMessage,
  ChatSuggestions,
  PatronStatus,
} from "@/lib/types";
import { useMarket } from "@/state/market-context";
import { cn } from "@/lib/utils";

export function ChatPage() {
  const { stream, settings } = useMarket();
  const snapshot = stream.snapshot;
  const symbol = settings?.symbol ?? snapshot?.symbol ?? "—";
  const timeframe = settings?.timeframe ?? snapshot?.timeframe ?? "M15";
  const digits = snapshot?.digits ?? 2;

  const conversations = usePolling<{ conversations: ChatConversation[] }>(
    "chat-conversations",
    () => api.chatConversations(),
    0,
  );
  const suggestions = usePolling<ChatSuggestions>(
    "chat-suggestions",
    () => api.chatSuggestions(),
    0,
  );
  const patron = usePolling<PatronStatus>("chat-patron", () => api.patronStatus(), 15_000);

  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const list = useMemo(
    () => conversations.data?.conversations ?? [],
    [conversations.data],
  );
  const active = list.find((conversation) => conversation.id === activeId) ?? null;

  useEffect(() => {
    if (!activeId && list.length > 0) setActiveId(list[0].id);
  }, [activeId, list]);

  useEffect(() => {
    if (!activeId) {
      setMessages([]);
      return;
    }
    let cancelled = false;
    api
      .chatMessages(activeId)
      .then((response) => {
        if (!cancelled) setMessages(response.messages);
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setError(cause instanceof ApiError ? cause.message : "Could not load messages.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [activeId]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const createConversation = async () => {
    setError(null);
    try {
      const created = await api.createConversation();
      conversations.reload();
      setActiveId(created.id);
      setMessages([]);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not create a conversation.");
    }
  };

  const send = async (text: string) => {
    const content = text.trim();
    if (!content) return;
    setError(null);
    let conversationId = activeId;
    if (!conversationId) {
      try {
        const created = await api.createConversation();
        conversationId = created.id;
        setActiveId(created.id);
        conversations.reload();
      } catch (cause) {
        setError(cause instanceof ApiError ? cause.message : "Could not start a conversation.");
        return;
      }
    }
    setSending(true);
    try {
      const result = await api.sendChatMessage(conversationId, content);
      setMessages((previous) => [...previous, result.user_message, result.assistant_message]);
      setInput("");
      conversations.reload();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Message could not be sent.");
    } finally {
      setSending(false);
    }
  };

  const removeConversation = async (id: string) => {
    try {
      await api.deleteConversation(id);
      conversations.reload();
      if (activeId === id) setActiveId(null);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not delete the conversation.");
    }
  };

  const clear = async () => {
    if (!activeId) return;
    try {
      await api.clearChatMessages(activeId);
      setMessages([]);
      conversations.reload();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not clear messages.");
    }
  };

  return (
    <div className="flex h-full min-h-0">
      <aside className="hidden w-[214px] shrink-0 flex-col border-r border-line bg-surface lg:flex">
        <header className="flex h-[30px] shrink-0 items-center gap-2 border-b border-line-soft px-2.5">
          <span className="label-xs">Conversations</span>
          <span className="num ml-auto text-[9px] text-ink-faint">{list.length}</span>
          <Button
            size="sm"
            variant="ghost"
            aria-label="New conversation"
            onClick={() => void createConversation()}
            icon={<MessageSquarePlus className="size-3.5" />}
          />
        </header>
        <div className="scroll-area min-h-0 flex-1 py-1">
          {list.map((conversation) => (
            <div
              key={conversation.id}
              className={cn(
                "group relative flex items-center border-b border-line-soft/60",
                conversation.id === activeId
                  ? "bg-light-blue"
                  : "hover:bg-soft",
              )}
            >
              {conversation.id === activeId && (
                <span className="absolute top-1/2 left-0 h-5 w-[2px] -translate-y-1/2 bg-accent" />
              )}
              <button
                type="button"
                onClick={() => setActiveId(conversation.id)}
                className="min-w-0 flex-1 px-2.5 py-2 text-left"
              >
                <p
                  className={cn(
                    "truncate text-[10.5px]",
                    conversation.id === activeId ? "text-ink" : "text-ink-muted",
                  )}
                >
                  {conversation.title}
                </p>
                <p className="mt-0.5 flex items-center gap-1.5 text-[8.5px] text-ink-faint">
                  <span className="num">{conversation.message_count ?? 0} msg</span>
                  <span className="size-[2px] rounded-full bg-ink-faint/50" />
                  <span className="num">{formatTimeOnly(conversation.updated_at)}</span>
                </p>
              </button>
              <button
                type="button"
                aria-label={`Delete ${conversation.title}`}
                onClick={() => void removeConversation(conversation.id)}
                className="mr-1.5 p-1 text-ink-faint opacity-0 transition-opacity group-hover:opacity-100 hover:text-warn"
              >
                <Trash2 className="size-3" aria-hidden />
              </button>
            </div>
          ))}
          {!list.length && (
            <p className="px-3 py-6 text-center text-[9.5px] leading-relaxed text-ink-faint">
              No transcripts yet.
              <br />
              Ask a question to begin.
            </p>
          )}
        </div>
        <footer className="border-t border-line-soft px-2.5 py-1.5 text-[9px] text-ink-faint">
          Local SQLite transcript
        </footer>
      </aside>

      <section className="flex min-w-0 flex-1 flex-col bg-chart">
        <header className="flex h-[34px] shrink-0 items-center gap-2 border-b border-line-soft bg-surface/60 px-3">
          <h2 className="min-w-0 truncate text-[11.5px] font-semibold text-ink">
            {active?.title ?? "New conversation"}
          </h2>
          <span className="hidden shrink-0 items-center gap-1.5 md:flex">
            <Badge tone="neutral">{symbol}</Badge>
            <Badge tone="muted">{timeframe}</Badge>
          </span>
          <div className="ml-auto flex shrink-0 items-center gap-2">
            <Badge tone="info">PATRON-grounded</Badge>
            {messages.length > 0 && (
              <Button size="sm" variant="ghost" onClick={() => void clear()}>
                Clear
              </Button>
            )}
          </div>
        </header>

        <AiNotice compact className="shrink-0" />

        <div ref={scrollRef} className="scroll-area min-h-0 flex-1 px-3 py-3">
          {!messages.length && (
            <div className="mx-auto max-w-xl py-8">
              <div className="flex items-center gap-2 text-ink-faint">
                <Bot className="size-4" aria-hidden />
                <p className="label-xs">Market research assistant</p>
              </div>
              <p className="mt-2 text-[13px] font-medium text-ink">
                Ask the live technical context a direct question.
              </p>
              <p className="mt-1 text-[10.5px] leading-relaxed text-ink-faint">
                Answers are deterministic text over the live snapshot, indicator values and the
                latest stored PATRON forecast. The assistant states when context or a model output
                is unavailable and never invents a forecast. Answers are stored locally.
              </p>
              <div className="mt-3 flex flex-col divide-y divide-line-soft border-y border-line-soft">
                {(suggestions.data?.suggestions ?? []).slice(0, 4).map((suggestion) => (
                  <button
                    key={suggestion.id}
                    type="button"
                    onClick={() => void send(suggestion.prompt)}
                    disabled={sending}
                    className="flex items-center gap-2 px-1 py-2 text-left text-[10.5px] text-ink-muted transition-colors hover:bg-surface hover:text-ink disabled:opacity-40"
                  >
                    <Sparkles className="size-3 shrink-0 text-accent/70" aria-hidden />
                    {suggestion.label}
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="space-y-3.5">
            {messages.map((message) => {
              const isUser = message.role === "user";
              return (
                <div key={message.id} className={cn("flex", isUser ? "justify-end" : "justify-start")}>
                  <div className={cn("min-w-0", isUser ? "max-w-[74%]" : "max-w-[82%]")}>
                    <div
                      className={cn(
                        "flex items-center gap-2 text-[9px] font-medium text-ink-faint",
                        isUser && "justify-end",
                      )}
                    >
                      <span>{isUser ? "You" : "KBMTI Analyst"}</span>
                      <span className="num normal-case tracking-normal">
                        {formatTimeOnly(message.created_at)}
                      </span>
                    </div>
                    <div
                      className={cn(
                        "mt-1 rounded-[8px] border px-3 py-2 text-[11px] leading-relaxed whitespace-pre-wrap",
                        isUser
                          ? "border-line bg-surface-2 text-ink"
                          : "border-line-soft border-l-2 border-l-accent/45 bg-surface text-ink-muted",
                      )}
                    >
                      {message.content}
                    </div>
                    {!isUser && (
                      <p className="mt-1 flex items-center gap-1.5 text-[9px] text-ink-faint">
                        <span className="size-1 rounded-full bg-accent/60" />
                        PATRON-grounded · {formatBrokerTime(message.created_at, true)} · {symbol}{" "}
                        {timeframe}
                      </p>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          {sending && (
            <div className="mt-3 flex items-center gap-2 text-[10px] text-ink-faint">
              <Spinner />
              Building an answer from the live snapshot and PATRON output…
            </div>
          )}
        </div>

        {error && (
          <p className="mx-3 mb-2 border border-warn/25 bg-warn/[0.05] px-2.5 py-1.5 text-[10px] text-warn/90">
            {error}
          </p>
        )}

        <form
          onSubmit={(event) => {
            event.preventDefault();
            void send(input);
          }}
          className="shrink-0 border-t border-line-soft bg-surface px-3 py-2.5"
        >
          <div className="flex items-end gap-1.5 rounded-[8px] border border-line bg-soft px-1 py-1 transition-colors focus-within:border-primary/60 focus-within:bg-surface">
            <label htmlFor="chat-input" className="sr-only">
              Chat message
            </label>
            <textarea
              id="chat-input"
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void send(input);
                }
              }}
              rows={1}
              maxLength={2000}
              placeholder="Ask about trend, RSI, the PATRON forecast or data freshness…"
              disabled={sending}
              className="max-h-24 min-h-[32px] flex-1 resize-none bg-transparent px-2 py-1.5 text-[11px] text-ink outline-none placeholder:text-ink-faint disabled:opacity-50"
            />
            <Button
              type="submit"
              size="md"
              variant="primary"
              disabled={sending || !input.trim()}
              icon={<Send className="size-3.5" />}
              aria-label="Send message"
            >
              Send
            </Button>
          </div>
          <div className="mt-1.5 flex items-center justify-between gap-3 text-[9px] text-ink-faint">
            <span>
              Deterministic · PATRON-grounding · context {symbol} {timeframe}
            </span>
            <span className="hidden sm:inline">Enter to send · Shift+Enter for newline</span>
          </div>
        </form>
      </section>

      <aside className="hidden w-[252px] shrink-0 flex-col overflow-y-auto border-l border-line bg-surface xl:flex">
        <GroupLabel>Context</GroupLabel>
        <DataRow label="Symbol" value={symbol} />
        <DataRow label="Timeframe" value={timeframe} />
        <DataRow label="Last price" value={formatPrice(snapshot?.last, digits)} />
        <DataRow
          label="Daily change"
          value={formatPercent(snapshot?.daily_change_percent)}
          toneClassName={
            (snapshot?.daily_change_percent ?? 0) > 0
              ? "text-bull"
              : (snapshot?.daily_change_percent ?? 0) < 0
                ? "text-bear"
                : "text-ink-muted"
          }
        />
        <DataRow label="Feed" value={snapshot?.data_state ?? "unavailable"} />
        <DataRow
          label="Data as of"
          value={formatBrokerTime(snapshot?.last_update, true)}
          hint="broker"
        />
        <DataRow label="Bars" value={`${stream.status?.poll_interval_seconds ?? 1}s poll`} />

        <GroupLabel>Suggested questions</GroupLabel>
        <div className="flex flex-col">
          {(suggestions.data?.suggestions ?? []).slice(0, 5).map((suggestion) => (
            <button
              key={suggestion.id}
              type="button"
              onClick={() => void send(suggestion.prompt)}
              disabled={sending}
              className="border-b border-line-soft/70 px-3 py-2 text-left text-[10px] leading-relaxed text-ink-muted transition-colors hover:bg-surface-2 hover:text-ink disabled:opacity-40"
            >
              {suggestion.label}
            </button>
          ))}
          {!suggestions.data?.suggestions.length && (
            <p className="px-3 py-2 text-[9.5px] text-ink-faint">
              Suggestions appear once market context is available.
            </p>
          )}
        </div>

        <div className="mt-auto border-t border-line-soft">
          <div className="flex items-center gap-2 border-b border-line-soft bg-surface-2/30 px-3 py-1.5">
            <MessagesSquare className="size-3 text-ink-faint" aria-hidden />
            <span className="label-xs">PATRON model</span>
          </div>
          <div className="space-y-1 px-3 py-2.5 text-[9.5px] text-ink-faint">
            <p className="flex justify-between gap-2">
              <span>State</span>
              <span className="num text-ink-muted">
                {patron.data?.state
                  ? patron.data.state.charAt(0) + patron.data.state.slice(1).toLowerCase()
                  : "Unknown"}
              </span>
            </p>
            <p className="flex justify-between gap-2">
              <span>Model</span>
              <span className="num text-ink-muted">{patron.data?.model_id ?? "patron-1.0.0"}</span>
            </p>
            <p className="flex justify-between gap-2">
              <span>Parameters</span>
              <span className="num text-ink-muted">
                {patron.data?.trainable_parameters?.toLocaleString() ?? "—"}
              </span>
            </p>
            <p className="flex justify-between gap-2">
              <span>Last inference</span>
              <span className="num text-ink-muted">
                {formatTimeOnly(patron.data?.last_inference_at)}
              </span>
            </p>
            <p className="mt-1 leading-relaxed">
              Replies are generated by deterministic rules grounded in PATRON's stored JSON, not by
              a language model. PATRON is a numerical forecaster and has no chat capability.
            </p>
          </div>
        </div>
      </aside>
    </div>
  );
}
