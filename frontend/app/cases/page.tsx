import Link from "next/link";
import { CASES } from "../_data/mock";
import { PageTitle, Pill } from "../_components/ui";

function stagePill(stage: string) {
  if (stage === "Settled") return <Pill tone="good">{stage}</Pill>;
  if (stage === "In suit") return <Pill tone="warn">{stage}</Pill>;
  return <Pill>{stage}</Pill>;
}

export default function CasesPage() {
  return (
    <div>
      <PageTitle
        title="Cases"
        subtitle={`${CASES.length} active matters`}
      />

      <div className="px-8 py-6">
        <div className="border border-line rounded-lg overflow-hidden">
          <div className="grid grid-cols-12 gap-4 px-5 py-3 border-b border-line bg-surface/40 text-[11px] text-muted font-medium">
            <div className="col-span-3">Client</div>
            <div className="col-span-2">Type</div>
            <div className="col-span-2">Stage</div>
            <div className="col-span-2 text-right">Value</div>
            <div className="col-span-1 text-right">Statute</div>
            <div className="col-span-2">Next</div>
          </div>
          <div className="divide-y divide-line">
            {CASES.map((c) => (
              <Link
                key={c.id}
                href={`/cases/${c.id}`}
                className="grid grid-cols-12 gap-4 px-5 py-4 items-center hover:bg-surface"
              >
                <div className="col-span-3">
                  <div className="text-[14px] font-medium">{c.client}</div>
                  <div className="text-[12px] text-muted mt-0.5 mono">
                    {c.id} · {c.carrier}
                  </div>
                </div>
                <div className="col-span-2 text-[13px]">{c.type}</div>
                <div className="col-span-2">{stagePill(c.stage)}</div>
                <div className="col-span-2 text-right text-[13px] tnum">
                  {c.value}
                </div>
                <div className="col-span-1 text-right text-[12px] text-muted tnum">
                  {c.statute}
                </div>
                <div className="col-span-2 text-[12.5px] text-muted">
                  {c.next}
                </div>
              </Link>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
