import { notFound } from "next/navigation";
import Link from "next/link";
import { CASES, CASE_TIMELINE, PRECEDENTS } from "../../_data/mock";
import { PageTitle, Pill, Card, SectionLabel } from "../../_components/ui";
import BrainSearch from "../../_components/brain-search";

export default async function CasePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const c = CASES.find((x) => x.id === id);
  if (!c) return notFound();

  return (
    <div>
      <PageTitle
        title={c.client}
        subtitle={`${c.id} · ${c.type} · ${c.carrier}`}
        right={<Pill>{c.stage}</Pill>}
      />

      <div className="px-8 py-6 grid grid-cols-12 gap-6">
        <div className="col-span-8 space-y-6">
          {/* Key facts */}
          <Card>
            <div className="px-5 py-4 border-b border-line">
              <SectionLabel>Key facts</SectionLabel>
            </div>
            <div className="px-5 py-5 grid grid-cols-3 gap-5 text-[13px]">
              <Field k="Mechanism" v={c.type} />
              <Field k="Carrier" v={c.carrier} />
              <Field k="Est. value" v={c.value} />
              <Field k="Stage" v={c.stage} />
              <Field k="Statute" v={c.statute} />
              <Field k="Next" v={c.next} />
            </div>
          </Card>

          {/* Timeline */}
          <Card>
            <div className="px-5 py-4 border-b border-line">
              <SectionLabel>Timeline</SectionLabel>
            </div>
            <div className="divide-y divide-line">
              {CASE_TIMELINE.map((t, i) => (
                <div
                  key={i}
                  className="grid grid-cols-12 px-5 py-3 items-baseline text-[13px]"
                >
                  <div className="col-span-2 text-muted tnum">{t.date}</div>
                  <div className="col-span-8">{t.what}</div>
                  <div className="col-span-2 text-right">
                    {t.ref && (
                      <Link
                        href={`/inbox/${t.ref}`}
                        className="text-[12px] text-muted hover:text-ink"
                      >
                        → {t.ref}
                      </Link>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </Card>

          {/* Comps */}
          <Card>
            <div className="px-5 py-4 border-b border-line flex items-center justify-between">
              <SectionLabel>Firm comps</SectionLabel>
              <span className="text-[11px] text-muted">
                Moss · matched on facts
              </span>
            </div>
            <div className="divide-y divide-line">
              {PRECEDENTS.map((p) => (
                <div
                  key={p.id}
                  className="grid grid-cols-12 gap-3 px-5 py-3 items-baseline text-[13px]"
                >
                  <div className="col-span-3 text-muted">{p.client}</div>
                  <div className="col-span-5">{p.facts}</div>
                  <div className="col-span-2 text-muted text-[12px]">
                    {p.outcome}
                  </div>
                  <div className="col-span-2 text-right tnum">{p.amount}</div>
                </div>
              ))}
            </div>
          </Card>
        </div>

        <aside className="col-span-4 space-y-6">
          <Card>
            <div className="px-5 py-4 border-b border-line">
              <SectionLabel>Parties</SectionLabel>
            </div>
            <div className="p-5 space-y-3 text-[13px]">
              <Field k="Client" v={c.client} />
              <Field k="Carrier" v={c.carrier} />
              <Field k="Adjuster" v="Janet S." />
              <Field k="Attorney" v="M. Reyes" />
              <Field k="Paralegal" v="Sue [agent]" />
            </div>
          </Card>

          <Card>
            <div className="px-5 py-4 border-b border-line">
              <SectionLabel>Documents</SectionLabel>
            </div>
            <div className="divide-y divide-line text-[13px]">
              <Doc name="Retainer agreement" status="Signed" />
              <Doc name="HIPAA authorization" status="Signed" />
              <Doc name="Police report" status="Requested" />
              <Doc name="Medical records · SF General" status="Received" />
              <Doc name="Medical records · Stanford" status="Pending" />
              <Doc name="Demand letter" status="Draft" />
            </div>
          </Card>

          <Card>
            <div className="px-5 py-4 border-b border-line">
              <SectionLabel>Ask the brain</SectionLabel>
            </div>
            <div className="p-5 text-[13px] text-muted leading-snug">
              Call <span className="mono text-ink">+1 (415) 200-LIEN</span> and
              ask anything. Voice agent answers from your firm&apos;s history in 5
              seconds.
            </div>
          </Card>

          <BrainSearch caseSlug="reyes-associates" clientName={c.client} />
        </aside>
      </div>
    </div>
  );
}

function Field({ k, v }: { k: string; v: string }) {
  return (
    <div>
      <div className="text-[11px] text-muted uppercase tracking-[0.08em]">
        {k}
      </div>
      <div className="mt-1 tnum">{v}</div>
    </div>
  );
}

function Doc({ name, status }: { name: string; status: string }) {
  const tone =
    status === "Signed" || status === "Received"
      ? "text-ink"
      : status === "Draft" || status === "Requested"
      ? "text-muted"
      : "text-warn";
  return (
    <div className="px-5 py-3 flex items-baseline justify-between">
      <span>{name}</span>
      <span className={`text-[12px] ${tone}`}>{status}</span>
    </div>
  );
}
