import Link from "next/link";
import { INTAKES } from "./_data/mock";
import { Card, Pill, Button, SectionLabel } from "./_components/ui";
import { LiveTimer } from "./_components/live-timer";

export default function TodayPage() {
  const liveAll = INTAKES.filter((i) => i.status === "live");
  const pending = INTAKES.filter((i) => i.status === "review");

  return (
    <div className="min-h-screen">
      <header className="px-8 pt-6 pb-4">
        <Link href="/" className="block">
          <span className="font-display text-[22px] tracking-tight leading-none">
            Lien
          </span>
          <span className="ml-3 text-[12px] text-muted">
            Reyes &amp; Associates
          </span>
        </Link>
      </header>

      <div className="px-8 py-4 space-y-6">
        {liveAll.length > 0 ? (
          <section>
            <div className="flex items-baseline justify-between mb-3">
              <h2 className="text-[15px] font-semibold tracking-tight">
                Currently on call
                <span className="ml-2 text-[13px] font-normal text-muted tnum">
                  {liveAll.length}
                </span>
              </h2>
            </div>
            <div className="grid grid-cols-3 gap-3">
              {liveAll.map((i) => (
                <LiveCard key={i.id} intake={i} />
              ))}
            </div>
          </section>
        ) : (
          <NoLiveHero />
        )}

        <section>
          <div className="flex items-baseline justify-between mb-2">
            <h2 className="text-[15px] font-semibold tracking-tight">
              Awaiting your approval
              <span className="ml-2 text-[13px] font-normal text-muted tnum">
                {pending.length}
              </span>
            </h2>
            <Link
              href="/inbox"
              className="text-[12px] text-muted hover:text-black"
            >
              See all intakes →
            </Link>
          </div>

          {pending.length === 0 ? (
            <Card className="p-6 text-center text-[13px] text-muted">
              No pending approvals. Everything is current.
            </Card>
          ) : (
            <div className="space-y-2">
              {pending.map((i) => (
                <Card key={i.id}>
                  <PendingRow intake={i} />
                </Card>
              ))}
            </div>
          )}
        </section>

        <section>
          <h2 className="text-[15px] font-semibold tracking-tight mb-2">
            How this works
          </h2>
          <div className="grid grid-cols-3 gap-3">
            <Card>
              <Step
                n="1"
                title="A call comes in"
                body="When someone dials your intake number, Sue picks up. The call streams here live so you can supervise from your desk."
                cta={{ label: "See the live view", href: liveAll[0] ? `/inbox/${liveAll[0].id}` : "/inbox" }}
              />
            </Card>
            <Card>
              <Step
                n="2"
                title="Copilot recommends a decision"
                body="It pulls comps, flags missing info, and pushes a one-tap approval to your phone when a case is hot."
                cta={{ label: "Try mobile approval", href: liveAll[0] ? `/approve/${liveAll[0].id}` : "/inbox" }}
              />
            </Card>
            <Card>
              <Step
                n="3"
                title="Accepted cases move forward"
                body="Retainer goes out via email, records requests fire automatically, and the case shows up in Cases."
                cta={{ label: "Open Cases", href: "/cases" }}
              />
            </Card>
          </div>
        </section>
      </div>
    </div>
  );
}

function LiveCard({ intake }: { intake: typeof INTAKES[number] }) {
  const [m, s] = intake.duration.split(":").map(Number);
  const startedSeconds = (m || 0) * 60 + (s || 0);
  const justStarted = startedSeconds < 60;

  return (
    <Card className="p-5 flex flex-col gap-4">
      <div className="flex items-center justify-between gap-2">
        <Pill tone="live">Currently on call</Pill>
        <span className="text-[12px] text-muted tnum">
          {intake.paralegal} · <LiveTimer start={intake.duration} />
        </span>
      </div>

      <div>
        <div className="font-display text-[24px] tracking-tight leading-tight">
          {intake.caller}
        </div>
        <div className="text-[12px] text-muted mt-1">{intake.source}</div>
      </div>

      <div className="grid grid-cols-3 gap-4 text-[12px]">
        <Fact k="Case" v={intake.caseType} />
        <Fact k="Carrier" v={intake.carrier ?? "—"} />
        <Fact k="Value" v={intake.valueRange} />
      </div>

      {intake.recommendation && (
        <div className="rounded-lg glass-inset p-4">
          <SectionLabel>Copilot recommendation</SectionLabel>
          <div className="mt-2 text-[13px] leading-snug">
            <span className="font-semibold">{intake.recommendation.verdict}.</span>{" "}
            {intake.recommendation.body}
          </div>
        </div>
      )}

      <div className="mt-auto flex flex-col gap-1.5">
        {!justStarted && (
          <Button
            variant="primary"
            href={`/approve/${intake.id}`}
            className="w-full"
          >
            Accept this case
          </Button>
        )}
        <Button
          variant={justStarted ? "primary" : "secondary"}
          href={`/inbox/${intake.id}`}
          className="w-full"
        >
          Need more info
        </Button>
      </div>
    </Card>
  );
}

function NoLiveHero() {
  return (
    <Card className="p-8">
      <SectionLabel>No live intakes right now</SectionLabel>
      <div className="mt-3 text-[16px] leading-snug max-w-xl">
        When a caller dials{" "}
        <span className="font-mono text-black">+1 (415) 200-LIEN</span> they
        appear here in real time. To try a demo intake, call that number and
        Sue will pick up.
      </div>
      <div className="mt-5 flex gap-2">
        <Button variant="primary" href="/inbox">
          Browse intakes
        </Button>
        <Button variant="secondary" href="/cases">
          See open cases
        </Button>
      </div>
    </Card>
  );
}

function PendingRow({ intake }: { intake: typeof INTAKES[number] }) {
  return (
    <div className="grid grid-cols-12 gap-3 px-5 py-4 items-center">
      <div className="col-span-3">
        <Link
          href={`/inbox/${intake.id}`}
          className="text-[14px] font-medium hover:underline"
        >
          {intake.caller}
        </Link>
        <div className="text-[12px] text-muted mt-0.5">{intake.source}</div>
      </div>
      <div className="col-span-3 text-[13px]">
        {intake.caseType}
        <div className="text-[12px] text-muted mt-0.5">{intake.carrier}</div>
      </div>
      <div className="col-span-2 text-[13px] tnum">
        {intake.valueRange}
        <div className="text-[12px] text-muted mt-0.5">Est. value</div>
      </div>
      <div className="col-span-1 text-[12px] text-muted tnum">
        {intake.duration}
      </div>
      <div className="col-span-3 flex gap-1.5 justify-end">
        <Button variant="secondary" href={`/inbox/${intake.id}`}>
          Review call
        </Button>
        <Button
          variant="primary"
          href={`/approve/${intake.id}`}
          target="_blank"
        >
          Decide ↗
        </Button>
      </div>
    </div>
  );
}

function Step({
  n,
  title,
  body,
  cta,
}: {
  n: string;
  title: string;
  body: string;
  cta: { label: string; href: string };
}) {
  return (
    <div className="p-5">
      <div className="text-[11px] mono text-muted tnum">{n}</div>
      <div className="mt-1 text-[14px] font-semibold tracking-tight">
        {title}
      </div>
      <p className="mt-2 text-[12.5px] text-muted leading-snug min-h-[60px]">
        {body}
      </p>
      <Link
        href={cta.href}
        className="mt-3 inline-block text-[12px] underline underline-offset-2 text-black hover:no-underline"
      >
        {cta.label} →
      </Link>
    </div>
  );
}

function Fact({ k, v }: { k: string; v: string }) {
  return (
    <div>
      <div className="text-[11px] text-muted uppercase tracking-[0.06em]">
        {k}
      </div>
      <div className="mt-1 tnum">{v}</div>
    </div>
  );
}
