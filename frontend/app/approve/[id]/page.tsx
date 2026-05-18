import { notFound } from "next/navigation";
import Link from "next/link";
import { INTAKES, PRECEDENTS } from "../../_data/mock";
import { AcceptActions } from "../../_components/accept-actions";

export default async function ApprovePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const intake = INTAKES.find((i) => i.id === id);
  if (!intake) return notFound();

  return (
    <div className="min-h-screen bg-surface flex items-start justify-center py-10 px-4">
      <div className="w-full max-w-[420px] bg-bg rounded-[36px] border border-line-strong shadow-[0_8px_32px_rgba(0,0,0,0.08)] overflow-hidden">
        {/* Phone status bar */}
        <div className="px-7 pt-3 pb-2 flex items-center justify-between text-[11px] text-muted">
          <span className="tnum">9:31</span>
          <span className="mono">Lien</span>
        </div>

        {/* Header */}
        <div className="px-7 pt-6 pb-5 border-b border-line">
          <div className="text-[11px] text-muted uppercase tracking-[0.08em]">
            New intake · live
          </div>
          <h1 className="mt-2 font-display text-[28px] tracking-tight leading-tight">
            Accept {intake.caller}?
          </h1>
          <p className="mt-2 text-[14px] text-muted leading-snug">
            Sue has them on the line right now. Recommend deciding before they
            speak to {intake.carrier ?? "the carrier"}.
          </p>
        </div>

        {/* Facts */}
        <div className="px-7 py-5 border-b border-line space-y-3">
          <Row k="Case"    v={intake.caseType} />
          <Row k="Value"   v={intake.valueRange} />
          <Row k="Carrier" v={intake.carrier ?? "—"} />
          <Row k="Statute" v={intake.statute?.label ?? "—"} />
          <Row k="Source"  v={intake.source} />
        </div>

        {/* Why */}
        <div className="px-7 py-5 border-b border-line">
          <div className="text-[11px] text-muted uppercase tracking-[0.08em]">
            Why our copilot recommends accept
          </div>
          <p className="mt-2 text-[14px] leading-snug">
            4 firm comps with this fact pattern · State Farm · ER + soft tissue ·
            avg <span className="font-medium tnum">$48,400</span>. No
            disqualifying flags.
          </p>

          <div className="mt-3 space-y-1.5">
            {PRECEDENTS.slice(0, 3).map((p) => (
              <div
                key={p.id}
                className="flex items-baseline justify-between text-[12.5px]"
              >
                <span className="text-muted">{p.client}</span>
                <span className="tnum">{p.amount}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Actions — wired to Supermemory + AgentMail */}
        <div className="px-7 py-5">
          <AcceptActions
            intake={{
              id: intake.id,
              caller: intake.caller,
              caseType: intake.caseType,
              carrier: intake.carrier,
              valueRange: intake.valueRange,
              statute: intake.statute,
              summary: intake.summary,
            }}
          />
        </div>

        <div className="px-7 pb-6 pt-2">
          <Link
            href={`/inbox/${intake.id}`}
            className="block text-center text-[12px] text-muted hover:text-ink"
          >
            See full transcript →
          </Link>
        </div>
      </div>
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex items-baseline justify-between">
      <span className="text-[13px] text-muted">{k}</span>
      <span className="text-[14px] tnum">{v}</span>
    </div>
  );
}

function Action({
  variant,
  label,
  sub,
}: {
  variant: "primary" | "secondary" | "ghost";
  label: string;
  sub: string;
}) {
  const styles = {
    primary: "bg-ink text-bg",
    secondary: "border border-line-strong text-ink bg-bg",
    ghost: "text-muted bg-bg",
  }[variant];
  return (
    <button
      className={`w-full px-5 py-4 rounded-xl text-left transition ${styles} active:scale-[0.99]`}
    >
      <div className="text-[16px] font-medium">{label}</div>
      <div
        className={`text-[12px] mt-0.5 ${
          variant === "primary" ? "text-bg/70" : "text-muted"
        }`}
      >
        {sub}
      </div>
    </button>
  );
}
