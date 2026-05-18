import { notFound } from "next/navigation";
import Link from "next/link";
import {
  INTAKES,
  TRANSCRIPT,
  PRECEDENTS,
  REQUIRED_INFO,
  WHISPER_SUGGESTIONS,
} from "../../_data/mock";
import { Button, Pill, SectionLabel } from "../../_components/ui";
import { WhisperPanel } from "../../_components/whisper";
import { LiveTimer } from "../../_components/live-timer";
import { StreamingTranscript } from "../../_components/streaming-transcript";
import { SendToMargarita } from "../../_components/send-to-margarita";

export default async function IntakePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const intake = INTAKES.find((i) => i.id === id);
  if (!intake) return notFound();

  const isLive = intake.status === "live";
  const needsReview = intake.status === "review";

  return (
    <div className="h-screen flex flex-col">
      {/* Top bar — no caller-name repetition; that lives in the left rail */}
      <header className="border-b border-line px-6 py-3 flex items-center justify-between bg-bg">
        <div className="flex items-center gap-3">
          <Link href="/inbox" className="text-[12px] text-muted hover:text-ink">
            ← Inbox
          </Link>
          <div className="h-3 w-px bg-line" />
          {isLive ? (
            <Pill tone="live">Currently on call</Pill>
          ) : needsReview ? (
            <Pill tone="warn">Needs approval</Pill>
          ) : (
            <Pill tone="good">{intake.decision?.outcome}</Pill>
          )}
          {isLive && (
            <span className="text-[12px] text-muted">
              <LiveTimer start={intake.duration} />
            </span>
          )}
          <span className="text-[12px] text-muted mono">{intake.callerPhone}</span>
          <span className="text-[12px] text-muted">· {intake.source}</span>
        </div>
        {isLive && (
          <SendToMargarita
            intake={{
              id: intake.id,
              caller: intake.caller,
              caseType: intake.caseType,
              carrier: intake.carrier,
              valueRange: intake.valueRange,
              statute: intake.statute,
            }}
          />
        )}
      </header>

      <div className="flex-1 grid grid-cols-12 min-h-0">
        {/* LEFT RAIL — single consolidated panel */}
        <aside className="col-span-3 border-r border-line overflow-y-auto">
          <div className="px-5 pt-5 pb-4 border-b border-line">
            <div className="font-display text-[24px] tracking-tight leading-none">
              {intake.caller}
            </div>
            <div className="mt-2 text-[12px] text-muted">
              {intake.caseType}
              {intake.carrier ? ` · ${intake.carrier}` : ""}
            </div>
            <div className="mt-1 text-[12px] text-muted">
              Handled by {intake.paralegal}
            </div>
          </div>

          <div className="px-5 py-4 border-b border-line grid grid-cols-2 gap-3">
            <KV k="Est. value" v={intake.valueRange} />
            <KV
              k="Statute"
              v={intake.statute?.label ?? "—"}
              tone={intake.statute?.label?.startsWith("0") ? "warn" : undefined}
            />
          </div>

          <div className="px-5 py-4">
            <div className="flex items-baseline justify-between mb-3">
              <SectionLabel>Required info</SectionLabel>
              <span className="text-[11px] text-muted tnum">
                {REQUIRED_INFO.filter((r) => r.status === "captured").length} /{" "}
                {REQUIRED_INFO.length}
              </span>
            </div>
            <ul className="space-y-2">
              {REQUIRED_INFO.map((f) => (
                <RequiredItem key={f.key} field={f} />
              ))}
            </ul>
          </div>
        </aside>

        {/* CENTER — transcript (live streaming) */}
        <section className="col-span-6 border-r border-line overflow-y-auto bg-bg flex flex-col">
          <div className="px-8 py-3 border-b border-line flex items-center justify-between bg-bg sticky top-0 z-10">
            <SectionLabel>Transcript</SectionLabel>
            {isLive && (
              <div className="flex items-center gap-1.5 text-[11px] text-muted">
                <span className="live-dot" />
                Streaming · AgentPhone
              </div>
            )}
          </div>

          {isLive ? (
            <StreamingTranscript
              transcript={TRANSCRIPT}
              callerName={intake.caller}
              paralegalName={intake.paralegal}
              speed={4}
            />
          ) : (
            <div className="px-8 py-6 space-y-4">
              {TRANSCRIPT.map((line, i) => (
                <div key={i} className="flex gap-4">
                  <div className="w-10 shrink-0 text-[11px] text-soft tnum mono pt-0.5">
                    {line.t}
                  </div>
                  <div className="flex-1">
                    <div className="text-[11px] font-medium text-muted">
                      {line.speaker === "Paralegal" ? intake.paralegal : intake.caller}
                    </div>
                    <div className="text-[14px] leading-snug mt-0.5">
                      {line.text}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* RIGHT — copilot — 4 tight blocks, no header */}
        <aside className="col-span-3 overflow-y-auto bg-surface/40 divide-y divide-line">
          {/* Recommendation */}
          {isLive && (
            <div className="px-5 py-5 bg-bg slide-up">
              <div className="flex items-baseline justify-between">
                <SectionLabel>Recommend accept</SectionLabel>
                <span className="text-[11px] text-muted">2 min ago</span>
              </div>
              <p className="mt-2 text-[13.5px] leading-snug">
                Strong fit. Fact pattern matches{" "}
                <span className="font-medium">4 firm comps</span> at avg{" "}
                <span className="font-medium tnum">$48,400</span>. Get the
                retainer signed before she hangs up.
              </p>
              <Button
                variant="primary"
                className="mt-3 w-full"
                href={`/approve/${intake.id}`}
                target="_blank"
              >
                Escalate to Margarita ↗
              </Button>
              <div className="mt-2 text-[11px] text-muted">
                iMessage + push · 5s delivery
              </div>
            </div>
          )}

          {/* Flags */}
          <div className="px-5 py-5">
            <SectionLabel>Flags</SectionLabel>
            <ul className="mt-3 space-y-3">
              <Flag
                tone="warn"
                title="Prior-injury disclosure"
                body="She mentioned a 2021 lifting strain. Scope it now before State Farm twists it into pre-existing."
              />
              <Flag
                tone="info"
                title="Statute clock"
                body="CA 2-yr · expires Apr 14, 2028 · 1y 11mo left."
              />
            </ul>
          </div>

          {/* Precedents */}
          <div className="px-5 py-5">
            <div className="flex items-baseline justify-between">
              <SectionLabel>Firm comps · Moss</SectionLabel>
              <span className="text-[11px] text-muted tnum">avg $48.4K</span>
            </div>
            <ul className="mt-3 space-y-2">
              {PRECEDENTS.map((p) => (
                <li
                  key={p.id}
                  className="grid grid-cols-12 gap-2 text-[12px] items-baseline"
                >
                  <span className="col-span-5 text-muted truncate">{p.client}</span>
                  <span className="col-span-4 text-muted truncate">{p.outcome.split(" (")[0]}</span>
                  <span className="col-span-3 text-right tnum">{p.amount}</span>
                </li>
              ))}
            </ul>
          </div>

          {/* Whisper — fires a real AgentPhone SMS */}
          <WhisperPanel
            agentName={intake.paralegal}
            suggestions={WHISPER_SUGGESTIONS}
            intakeId={intake.id}
          />
        </aside>
      </div>
    </div>
  );
}

function KV({
  k,
  v,
  tone,
}: {
  k: string;
  v: string;
  tone?: "warn";
}) {
  return (
    <div>
      <div className="text-[11px] text-muted">{k}</div>
      <div
        className={`mt-0.5 text-[13px] tnum ${tone === "warn" ? "text-warn" : ""}`}
      >
        {v}
      </div>
    </div>
  );
}

function RequiredItem({ field }: { field: (typeof REQUIRED_INFO)[number] }) {
  const labelClass =
    field.status === "captured" || field.status === "partial"
      ? "text-ink"
      : field.status === "flagged"
      ? "text-warn"
      : field.status === "capturing"
      ? "text-ink"
      : "text-muted";

  return (
    <li className="flex items-start gap-2.5 text-[12.5px]">
      <Indicator status={field.status} />
      <div className="flex-1 min-w-0">
        <div className={`leading-tight ${labelClass}`}>
          {field.label}
          {field.status === "capturing" && (
            <span className="ml-2 text-[10px] text-muted uppercase tracking-wider">
              capturing
            </span>
          )}
        </div>
        {field.detail && (
          <div
            className={`text-[11.5px] mt-0.5 leading-snug ${
              field.status === "flagged" ? "text-warn/80" : "text-muted"
            }`}
          >
            {field.detail}
          </div>
        )}
      </div>
    </li>
  );
}

function Indicator({ status }: { status: (typeof REQUIRED_INFO)[number]["status"] }) {
  if (status === "captured") {
    return (
      <span className="mt-[3px] w-3.5 h-3.5 rounded-full border border-ink bg-ink flex items-center justify-center shrink-0">
        <svg viewBox="0 0 10 10" className="w-2 h-2 text-white">
          <path
            d="M2 5 L4.2 7 L8 3"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </span>
    );
  }
  if (status === "partial") {
    return (
      <span className="mt-[3px] w-3.5 h-3.5 rounded-full border border-ink bg-bg flex items-center justify-center shrink-0">
        <span className="w-[7px] h-[7px] rounded-full bg-ink" />
      </span>
    );
  }
  if (status === "capturing") {
    return (
      <span className="mt-[3px] w-3.5 h-3.5 rounded-full border-2 border-ink border-dashed bg-bg shrink-0" />
    );
  }
  if (status === "flagged") {
    return (
      <span className="mt-[3px] w-3.5 h-3.5 rounded-full border border-warn bg-bg flex items-center justify-center shrink-0">
        <span className="text-warn font-bold text-[9px] leading-none">!</span>
      </span>
    );
  }
  return (
    <span className="mt-[3px] w-3.5 h-3.5 rounded-full border border-line-strong bg-bg shrink-0" />
  );
}

function Flag({
  tone,
  title,
  body,
}: {
  tone: "warn" | "info";
  title: string;
  body: string;
}) {
  return (
    <li className="flex gap-2.5">
      <span
        className={`mt-1 w-1 self-stretch rounded-full ${
          tone === "warn" ? "bg-warn" : "bg-line-strong"
        } shrink-0`}
      />
      <div className="flex-1">
        <div
          className={`text-[12.5px] font-medium leading-tight ${
            tone === "warn" ? "text-warn" : ""
          }`}
        >
          {title}
        </div>
        <div className="mt-1 text-[12px] text-muted leading-snug">{body}</div>
      </div>
    </li>
  );
}
