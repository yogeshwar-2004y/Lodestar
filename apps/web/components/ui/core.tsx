"use client";

import * as DialogPrimitive from "@radix-ui/react-dialog";
import * as SwitchPrimitive from "@radix-ui/react-switch";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { AlertTriangle, CheckCircle2, Info, X, XCircle } from "lucide-react";
import * as React from "react";

import { cn } from "@/lib/utils";

/* ------------------------------------------------------------------ inputs */

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(({ className, ...props }, ref) => (
  <input
    ref={ref}
    className={cn(
      "h-9 w-full rounded-[10px] border border-border bg-surface px-3 text-sm text-fg placeholder:text-fg-subtle transition-colors",
      "hover:border-border-strong focus-visible:border-accent focus-visible:outline-2 focus-visible:outline-ring/40 disabled:opacity-50",
      className,
    )}
    {...props}
  />
));
Input.displayName = "Input";

export const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(({ className, ...props }, ref) => (
  <textarea
    ref={ref}
    className={cn(
      "min-h-[88px] w-full rounded-[10px] border border-border bg-surface px-3 py-2 text-sm text-fg placeholder:text-fg-subtle",
      "hover:border-border-strong focus-visible:border-accent focus-visible:outline-2 focus-visible:outline-ring/40",
      className,
    )}
    {...props}
  />
));
Textarea.displayName = "Textarea";

export function Label({ className, ...props }: React.LabelHTMLAttributes<HTMLLabelElement>) {
  return <label className={cn("mb-1.5 block text-[13px] font-medium text-fg", className)} {...props} />;
}

export function Field({ label, hint, error, children, htmlFor }: { label: string; hint?: React.ReactNode; error?: string; children: React.ReactNode; htmlFor?: string }) {
  return (
    <div>
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
      {error ? <p className="mt-1 text-xs text-danger" role="alert">{error}</p> : hint ? <p className="mt-1 text-xs text-fg-subtle">{hint}</p> : null}
    </div>
  );
}

export function NativeSelect({ className, ...props }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn("h-9 rounded-[10px] border border-border bg-surface px-3 pr-8 text-sm text-fg hover:border-border-strong", className)}
      {...props}
    />
  );
}

export function Switch({ checked, onCheckedChange, label, disabled }: { checked: boolean; onCheckedChange: (v: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <SwitchPrimitive.Root
      checked={checked}
      onCheckedChange={onCheckedChange}
      disabled={disabled}
      aria-label={label}
      className="relative inline-flex h-5 w-9 shrink-0 items-center rounded-full bg-border-strong transition-colors data-[state=checked]:bg-accent disabled:opacity-50"
    >
      <SwitchPrimitive.Thumb className="block size-4 translate-x-0.5 rounded-full bg-white shadow transition-transform data-[state=checked]:translate-x-[18px]" />
    </SwitchPrimitive.Root>
  );
}

/* ------------------------------------------------------------------ surfaces */

export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("rounded-[var(--radius)] border border-border bg-surface shadow-card", className)} {...props} />;
}

export function CardHeader({ title, description, action, className }: { title: React.ReactNode; description?: React.ReactNode; action?: React.ReactNode; className?: string }) {
  return (
    <div className={cn("flex items-start justify-between gap-4 px-5 pt-4 pb-3", className)}>
      <div className="min-w-0">
        <h3 className="text-[15px] font-semibold tracking-tight text-fg">{title}</h3>
        {description && <p className="mt-0.5 text-[13px] text-fg-muted">{description}</p>}
      </div>
      {action}
    </div>
  );
}

export function CardBody({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("px-5 pb-5", className)} {...props} />;
}

const badgeTones = {
  neutral: "bg-bg-subtle text-fg-muted border-border",
  accent: "bg-accent-soft text-accent border-accent/20",
  teal: "bg-teal-soft text-teal border-teal/20",
  success: "bg-success-soft text-success border-success/20",
  warning: "bg-warning-soft text-warning border-warning/25",
  danger: "bg-danger-soft text-danger border-danger/20",
  info: "bg-info-soft text-info border-info/20",
} as const;
export type Tone = keyof typeof badgeTones;

export function Badge({ tone = "neutral", className, children, dot }: { tone?: Tone; className?: string; children: React.ReactNode; dot?: boolean }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11.5px] font-medium leading-4 whitespace-nowrap", badgeTones[tone], className)}>
      {dot && <span className="size-1.5 rounded-full bg-current" aria-hidden />}
      {children}
    </span>
  );
}

const alertIcons = { info: Info, success: CheckCircle2, warning: AlertTriangle, danger: XCircle } as const;
export function Alert({ tone = "info", title, children, className, action }: { tone?: keyof typeof alertIcons; title?: React.ReactNode; children?: React.ReactNode; className?: string; action?: React.ReactNode }) {
  const Icon = alertIcons[tone];
  const tones = { info: "bg-info-soft border-info/20 text-info", success: "bg-success-soft border-success/20 text-success", warning: "bg-warning-soft border-warning/25 text-warning", danger: "bg-danger-soft border-danger/20 text-danger" };
  return (
    <div role={tone === "danger" ? "alert" : "status"} className={cn("flex gap-3 rounded-[10px] border px-4 py-3 text-sm", tones[tone], className)}>
      <Icon className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1 text-fg">
        {title && <p className="font-medium">{title}</p>}
        {children && <div className="text-fg-muted [&_a]:underline">{children}</div>}
      </div>
      {action}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("skeleton rounded-md", className)} aria-hidden />;
}

export function EmptyState({ icon: Icon, title, children, action }: { icon: React.ComponentType<{ className?: string }>; title: string; children?: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      <div className="mb-4 grid size-12 place-items-center rounded-2xl border border-border bg-bg-subtle">
        <Icon className="size-5 text-fg-muted" />
      </div>
      <h3 className="text-[15px] font-semibold">{title}</h3>
      {children && <p className="mt-1 max-w-sm text-[13px] text-fg-muted">{children}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function Kbd({ children }: { children: React.ReactNode }) {
  return <kbd className="rounded border border-border bg-bg-subtle px-1.5 py-0.5 font-mono text-[10.5px] text-fg-muted">{children}</kbd>;
}

export function DemoBadge({ label = "Demo data" }: { label?: string }) {
  return <Badge tone="warning" dot>{label}</Badge>;
}

/* ------------------------------------------------------------------ tabs / tooltip */

export const Tabs = TabsPrimitive.Root;
export function TabsList({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.List>) {
  return <TabsPrimitive.List className={cn("inline-flex h-9 items-center gap-1 rounded-[10px] border border-border bg-bg-subtle p-1", className)} {...props} />;
}
export function TabsTrigger({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      className={cn("rounded-[7px] px-3 py-1 text-[13px] font-medium text-fg-muted transition-colors hover:text-fg data-[state=active]:bg-surface data-[state=active]:text-fg data-[state=active]:shadow-sm", className)}
      {...props}
    />
  );
}
export const TabsContent = TabsPrimitive.Content;

export function Tooltip({ content, children }: { content: React.ReactNode; children: React.ReactNode }) {
  return (
    <TooltipPrimitive.Provider delayDuration={250}>
      <TooltipPrimitive.Root>
        <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
        <TooltipPrimitive.Portal>
          <TooltipPrimitive.Content sideOffset={6} className="z-50 max-w-xs rounded-md bg-fg px-2.5 py-1.5 text-xs text-bg shadow-lg">
            {content}
          </TooltipPrimitive.Content>
        </TooltipPrimitive.Portal>
      </TooltipPrimitive.Root>
    </TooltipPrimitive.Provider>
  );
}

/* ------------------------------------------------------------------ dialogs & drawers */

export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogClose = DialogPrimitive.Close;

export function DialogContent({ title, description, children, className, side }: { title: string; description?: React.ReactNode; children: React.ReactNode; className?: string; side?: "right" }) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-black/30 backdrop-blur-[2px] data-[state=open]:animate-in" />
      <DialogPrimitive.Content
        className={cn(
          "fixed z-50 border border-border bg-surface shadow-2xl focus:outline-none",
          side === "right"
            ? "inset-y-0 right-0 h-full w-full max-w-xl overflow-y-auto"
            : "left-1/2 top-1/2 max-h-[85vh] w-[calc(100vw-32px)] max-w-lg -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-2xl",
          className,
        )}
      >
        <div className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
          <div>
            <DialogPrimitive.Title className="text-base font-semibold">{title}</DialogPrimitive.Title>
            {description ? (
              <DialogPrimitive.Description className="mt-0.5 text-[13px] text-fg-muted">{description}</DialogPrimitive.Description>
            ) : (
              <DialogPrimitive.Description className="sr-only">{title}</DialogPrimitive.Description>
            )}
          </div>
          <DialogPrimitive.Close className="rounded-md p-1 text-fg-muted hover:bg-bg-subtle hover:text-fg" aria-label="Close">
            <X className="size-4" />
          </DialogPrimitive.Close>
        </div>
        <div className="p-5">{children}</div>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}

/* ------------------------------------------------------------------ table */

export function Table({ className, ...props }: React.TableHTMLAttributes<HTMLTableElement>) {
  return (
    <div className="w-full overflow-x-auto">
      <table className={cn("w-full border-collapse text-left text-[13px]", className)} {...props} />
    </div>
  );
}
export function Th({ className, ...props }: React.ThHTMLAttributes<HTMLTableCellElement>) {
  return <th className={cn("border-b border-border bg-surface-2 px-4 py-2.5 text-[11.5px] font-medium uppercase tracking-wide text-fg-subtle", className)} {...props} />;
}
export function Td({ className, ...props }: React.TdHTMLAttributes<HTMLTableCellElement>) {
  return <td className={cn("border-b border-border px-4 py-3 align-middle", className)} {...props} />;
}

/* ------------------------------------------------------------------ stepper */

export function Stepper({ steps, current }: { steps: string[]; current: number }) {
  return (
    <ol className="flex flex-wrap items-center gap-2" aria-label="Progress">
      {steps.map((s, i) => {
        const state = i < current ? "done" : i === current ? "current" : "todo";
        return (
          <li key={s} className="flex items-center gap-2" aria-current={state === "current" ? "step" : undefined}>
            <span
              className={cn(
                "grid size-6 place-items-center rounded-full border text-[11px] font-semibold tabular",
                state === "done" && "border-success bg-success text-white",
                state === "current" && "border-accent bg-accent-soft text-accent",
                state === "todo" && "border-border text-fg-subtle",
              )}
            >
              {state === "done" ? "✓" : i + 1}
            </span>
            <span className={cn("text-[13px]", state === "todo" ? "text-fg-subtle" : "font-medium text-fg")}>{s}</span>
            {i < steps.length - 1 && <span className="mx-1 h-px w-6 bg-border" aria-hidden />}
          </li>
        );
      })}
    </ol>
  );
}
