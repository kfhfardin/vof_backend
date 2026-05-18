import Link from "next/link";
import { INTAKES } from "../_data/mock";
import { PageTitle, Pill } from "../_components/ui";

function statusPill(status: string) {
  if (status === "live") return <Pill tone="live">Currently on call</Pill>;
  if (status === "review") return <Pill tone="warn">Needs approval</Pill>;
  if (status === "approved") return <Pill tone="good">Accepted</Pill>;
  return <Pill>Declined</Pill>;
}

export default function InboxPage() {
  const live = INTAKES.filter((i) => i.status === "live");
  const review = INTAKES.filter((i) => i.status === "review");
  const closed = INTAKES.filter((i) => i.status === "approved" || i.status === "declined");

  return (
    <div>
      <PageTitle title="Inbox" subtitle="Live and recent intakes" />

      <div className="px-8 py-6 space-y-8">
        <Group title="Live" items={live} />
        <Group title="Needs your approval" items={review} />
        <Group title="Earlier" items={closed} />
      </div>
    </div>
  );
}

function Group({ title, items }: { title: string; items: typeof INTAKES }) {
  if (items.length === 0) return null;
  return (
    <section>
      <div className="flex items-baseline justify-between mb-2">
        <h2 className="text-[13px] font-medium text-muted">{title}</h2>
        <span className="text-[11px] text-soft tnum">{items.length}</span>
      </div>
      <div className="border border-line rounded-lg overflow-hidden bg-bg">
        {items.map((i, idx) => (
          <Link
            key={i.id}
            href={`/inbox/${i.id}`}
            className={`grid grid-cols-12 gap-4 px-5 py-4 items-center hover:bg-surface ${
              idx < items.length - 1 ? "border-b border-line" : ""
            }`}
          >
            <div className="col-span-3">
              <div className="text-[14px] font-medium">{i.caller}</div>
              <div className="text-[12px] text-muted mt-0.5">{i.source}</div>
            </div>
            <div className="col-span-3">
              <div className="text-[13px]">{i.caseType}</div>
              <div className="text-[12px] text-muted mt-0.5">{i.carrier ?? "—"}</div>
            </div>
            <div className="col-span-2">
              <div className="text-[13px] tnum">{i.valueRange}</div>
              <div className="text-[12px] text-muted mt-0.5">Est. value</div>
            </div>
            <div className="col-span-2 text-[12px] text-muted">
              <div className="tnum">{i.startedAt}</div>
              <div className="mt-0.5 tnum">{i.duration}</div>
            </div>
            <div className="col-span-2 flex justify-end">{statusPill(i.status)}</div>
          </Link>
        ))}
      </div>
    </section>
  );
}
