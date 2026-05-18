import Link from "next/link";

export function PageTitle({
  title,
  subtitle,
  right,
}: {
  title: string;
  subtitle?: string;
  right?: React.ReactNode;
}) {
  return (
    <div className="px-8 pt-8 pb-6 flex items-end justify-between gap-6">
      <div>
        <h1 className="font-display text-[36px] tracking-tight leading-none">
          {title}
        </h1>
        {subtitle && (
          <p className="mt-2 text-[13px] text-muted">{subtitle}</p>
        )}
      </div>
      {right && <div>{right}</div>}
    </div>
  );
}

export function Pill({
  children,
  tone = "neutral",
}: {
  children: React.ReactNode;
  tone?: "neutral" | "live" | "warn" | "good";
}) {
  const styles = {
    neutral: "bg-white/10 text-white/80 border border-white/15",
    live: "bg-white text-black border border-white",
    warn: "bg-warn/15 text-warn border border-warn/40",
    good: "bg-white/15 text-white border border-white/20",
  }[tone];
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium ${styles}`}
    >
      {children}
    </span>
  );
}

export function Button({
  children,
  variant = "secondary",
  href,
  target,
  className = "",
  ...props
}: {
  children: React.ReactNode;
  variant?: "primary" | "secondary" | "ghost";
  href?: string;
  target?: string;
  className?: string;
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const base =
    "inline-flex items-center justify-center gap-2 px-3 py-1.5 rounded-md text-[13px] font-medium transition-colors";
  const styles = {
    primary: "bg-white text-black hover:bg-white/90",
    secondary: "text-white bg-white/8 hover:bg-white/14 backdrop-blur-md",
    ghost: "text-white/70 hover:text-white hover:bg-white/8",
  }[variant];
  const cls = `${base} ${styles} ${className}`;
  if (href) {
    return (
      <Link href={href} target={target} className={cls}>
        {children}
      </Link>
    );
  }
  return (
    <button className={cls} {...props}>
      {children}
    </button>
  );
}

export function Card({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={`rounded-2xl glass text-white ${className}`}>
      {children}
    </div>
  );
}

export function StatCard({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <Card className="p-5">
      <div className="text-[12px] text-muted">{label}</div>
      <div className="mt-3 text-[34px] font-semibold tracking-tight tnum leading-none">
        {value}
      </div>
      {sub && <div className="mt-2 text-[12px] text-muted">{sub}</div>}
    </Card>
  );
}

export function Kbd({ children }: { children: React.ReactNode }) {
  return <span className="kbd">{children}</span>;
}

export function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[11px] font-medium text-muted uppercase tracking-[0.08em]">
      {children}
    </div>
  );
}
