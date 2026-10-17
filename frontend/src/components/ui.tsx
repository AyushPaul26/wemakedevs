import { useRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import {
  FileText,
  LoaderCircle,
  X,
  ArrowUpRight,
  CircleAlert,
} from "lucide-react";
import type { Source } from "../types";
export function Button({
  children,
  className = "",
  variant = "secondary",
  busy,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost";
  busy?: boolean;
}) {
  return (
    <button
      type="button"
      {...props}
      disabled={props.disabled || busy}
      aria-busy={busy || undefined}
      className={`button button-${variant} ${className}`}
    >
      <span className={busy ? "button-content busy-content" : "button-content"}>
        {children}
      </span>
      {busy && (
        <LoaderCircle
          size={16}
          className="spin button-spinner"
          aria-hidden="true"
        />
      )}
    </button>
  );
}
const dialogOpeners = new WeakMap<HTMLElement, HTMLElement>();
/** Preserve the original trigger when one dialog navigates into another. */
export function dialogReturnTarget(
  element: HTMLElement | null,
): HTMLElement | null {
  const parent = element?.closest<HTMLElement>('[role="dialog"]');
  return (parent && dialogOpeners.get(parent)) || element;
}
export function Modal({
  open,
  onOpenChange,
  title,
  description,
  children,
  wide = false,
  returnFocusTo,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  children: ReactNode;
  wide?: boolean;
  returnFocusTo?: HTMLElement | null;
}) {
  const returnFocus = useRef<HTMLElement | null>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="modal-overlay" />
        <Dialog.Content
          ref={contentRef}
          onOpenAutoFocus={() => {
            returnFocus.current =
              returnFocusTo ||
              dialogReturnTarget(document.activeElement as HTMLElement);
            if (contentRef.current && returnFocus.current)
              dialogOpeners.set(contentRef.current, returnFocus.current);
          }}
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            if (returnFocus.current?.isConnected) returnFocus.current.focus();
          }}
          className={`modal-content ${wide ? "modal-wide" : ""}`}
          {...(description ? {} : { "aria-describedby": undefined })}
        >
          <div className="modal-heading">
            <div>
              <Dialog.Title>{title}</Dialog.Title>
              {description && (
                <Dialog.Description>{description}</Dialog.Description>
              )}
            </div>
            <Dialog.Close asChild>
              <Button
                variant="ghost"
                className="icon-button"
                aria-label="Close dialog"
                onClick={() => onOpenChange(false)}
              >
                <X size={20} />
              </Button>
            </Dialog.Close>
          </div>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
export function Status({
  children,
  error = false,
}: {
  children: ReactNode;
  error?: boolean;
}) {
  return (
    <div
      className={`status-message ${error ? "status-error" : ""}`}
      role={error ? "alert" : "status"}
    >
      {error ? (
        <CircleAlert size={17} />
      ) : (
        <LoaderCircle size={17} className="spin" />
      )}
      <span>{children}</span>
    </div>
  );
}
export function Empty({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="empty-state">
      <span className="empty-icon">
        <FileText size={24} />
      </span>
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}
export function SourceButton({
  id,
  sources,
  onSource,
  compact = false,
}: {
  id: string;
  sources: Source[];
  onSource: (id: string) => void;
  compact?: boolean;
}) {
  const source = sources.find((item) => item.id === id);
  return (
    <button
      className={`source-link ${compact ? "compact" : ""}`}
      onClick={() => onSource(id)}
    >
      <FileText size={14} />
      <span>{source?.title ?? "View source"}</span>
      <ArrowUpRight size={13} />
    </button>
  );
}
