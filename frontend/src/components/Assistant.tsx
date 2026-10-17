import { createContext, useContext, useRef, useState } from "react";
import {
  AssistantRuntimeProvider,
  ComposerPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  useAuiState,
  useExternalStoreRuntime,
  type ThreadMessageLike,
} from "@assistant-ui/react";
import {
  ArrowUp,
  ArrowUpRight,
  Check,
  ChevronDown,
  GitBranch,
  Sparkles,
} from "lucide-react";
import type { Investigation, Source } from "../types";
import { api, errorMessage } from "../api";
import { SourceButton, Status } from "./ui";
const EvidenceContext = createContext<{
  sources: Source[];
  onSource: (id: string) => void;
  onActions: () => void;
}>({ sources: [], onSource: () => {}, onActions: () => {} });
function AssistantMessage() {
  const { sources, onSource, onActions } = useContext(EvidenceContext);
  const investigation = useAuiState(
    (state) =>
      state.message.metadata.custom?.investigation as Investigation | undefined,
  );
  return (
    <MessagePrimitive.Root className="assistant-message">
      <div className="message-author">
        <span className="mini-relay">
          <Sparkles size={13} />
        </span>
        Relay
        <span className="message-mode">
          {investigation?.mode === "live" ? "Live model" : "Guided demo"}
        </span>
      </div>
      <div className="message-text">
        <MessagePrimitive.Parts />
      </div>
      {investigation && (
        <>
          <div className="source-list">
            {investigation.source_ids.map((id) => (
              <SourceButton
                key={id}
                id={id}
                sources={sources}
                onSource={onSource}
                compact
              />
            ))}
          </div>
          <details className="agent-steps">
            <summary>
              <GitBranch size={14} />
              {investigation.steps.length} agent steps
              <ChevronDown size={13} />
            </summary>
            <ol>
              {investigation.steps.map((step, index) => (
                <li key={`${step.agent}-${index}`}>
                  <span className={`step-dot ${step.status}`}>
                    {step.status === "complete" ? (
                      <Check size={10} />
                    ) : (
                      index + 1
                    )}
                  </span>
                  <div>
                    <strong>{step.label}</strong>
                    <p>{step.detail}</p>
                    <small>
                      {step.agent} · {step.status}
                    </small>
                  </div>
                </li>
              ))}
            </ol>
          </details>
          {investigation.actions.length > 0 && (
            <button className="assistant-action-link" onClick={onActions}>
              {investigation.actions.length} proposed tasks · Review actions
              <ArrowUpRight size={14} />
            </button>
          )}
          <div className="saved-note">
            <Check size={12} />
            Saved to company memory
          </div>
        </>
      )}
    </MessagePrimitive.Root>
  );
}
function UserMessage() {
  return (
    <MessagePrimitive.Root className="user-message">
      <MessagePrimitive.Parts />
    </MessagePrimitive.Root>
  );
}
export function Assistant({
  sources,
  mode,
  onSource,
  onResult,
  onActions,
}: {
  sources: Source[];
  mode: "demo" | "live";
  onSource: (id: string) => void;
  onResult: (result: Investigation) => void;
  onActions: () => void;
}) {
  const [messages, setMessages] = useState<ThreadMessageLike[]>([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const active = useRef(false);
  const session = useRef(crypto.randomUUID());
  const runtime = useExternalStoreRuntime({
    messages,
    convertMessage: (message) => message,
    isRunning: running,
    isSendDisabled: running,
    onNew: async (message) => {
      if (active.current) return;
      const question = message.content
        .filter((part) => part.type === "text")
        .map((part) => (part.type === "text" ? part.text : ""))
        .join("\n")
        .trim();
      if (!question) return;
      if (question.length > 2000) {
        setError("Keep your question under 2,000 characters.");
        return;
      }
      active.current = true;
      setRunning(true);
      setError("");
      const userId = crypto.randomUUID();
      setMessages((current) => [
        ...current,
        { id: userId, role: "user", content: question },
      ]);
      try {
        const result = await api.investigate(question, session.current);
        setMessages((current) => [
          ...current,
          {
            id: result.id,
            role: "assistant",
            content: result.answer,
            status: { type: "complete", reason: "stop" },
            metadata: { custom: { investigation: result } },
          },
        ]);
        onResult(result);
      } catch (err) {
        setError(errorMessage(err));
        setMessages((current) => current.filter((item) => item.id !== userId));
        runtime.thread.composer.setText(question);
      } finally {
        active.current = false;
        setRunning(false);
      }
    },
  });
  const suggestions = [
    "What could block the Atlas launch?",
    "Who owns the payment gateway?",
    "What happened in the last payment incident?",
  ];
  return (
    <aside className="assistant-panel" aria-label="Relay assistant">
      <div className="assistant-heading">
        <div className="assistant-symbol">
          <Sparkles size={19} />
        </div>
        <div>
          <h2>Ask Relay</h2>
          <span>Your company, in context</span>
        </div>
        <span
          className="assistant-status"
          title="Responses are backed by company sources"
        />
      </div>
      <AssistantRuntimeProvider runtime={runtime}>
        <EvidenceContext.Provider value={{ sources, onSource, onActions }}>
          <ThreadPrimitive.Root className="assistant-thread">
            <ThreadPrimitive.Viewport className="assistant-viewport">
              <div className="assistant-intro">
                <span className="eyebrow">
                  A LITTLE CONTEXT GOES A LONG WAY
                </span>
                <h3>
                  Connect the dots.
                  <br />
                  Find your next move.
                </h3>
                <p>
                  Ask about a launch, a decision, or the people behind it. I’ll
                  bring the evidence.
                </p>
              </div>
              {messages.length === 0 && (
                <div className="suggested-questions">
                  {suggestions.map((question) => (
                    <button
                      key={question}
                      onClick={() => {
                        runtime.thread.composer.setText(question);
                        runtime.thread.composer.send();
                      }}
                      disabled={running}
                    >
                      <span>{question}</span>
                      <ArrowUpRight size={15} />
                    </button>
                  ))}
                </div>
              )}
              <ThreadPrimitive.Messages
                components={{ UserMessage, AssistantMessage }}
              />
              {running && <Status>Investigating company sources…</Status>}
              {error && <Status error>{error}</Status>}
            </ThreadPrimitive.Viewport>
            <div className="composer-area">
              <div className="mode-notice">
                <span className={`mode-dot ${mode}`} />
                {mode === "demo"
                  ? "Guided demo · source-backed responses"
                  : "Live model · source-backed responses"}
              </div>
              <ComposerPrimitive.Root className="composer" noValidate>
                <ComposerPrimitive.Input
                  placeholder="Ask about your company…"
                  aria-label="Ask Relay a question"
                  maxLength={2000}
                  rows={2}
                  autoFocus={false}
                  addAttachmentOnPaste={false}
                  disabled={running}
                />
                <div className="composer-bottom">
                  <span>Company knowledge only</span>
                  <ComposerPrimitive.Send
                    className="send-button"
                    aria-label="Send question"
                  >
                    <ArrowUp size={18} />
                  </ComposerPrimitive.Send>
                </div>
              </ComposerPrimitive.Root>
              <p className="composer-footnote">
                Evidence first. Your approval before action.
              </p>
            </div>
          </ThreadPrimitive.Root>
        </EvidenceContext.Provider>
      </AssistantRuntimeProvider>
    </aside>
  );
}
