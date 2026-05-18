"use client";

import { useEffect, useState } from "react";

function parse(mmss: string): number {
  const [m, s] = mmss.split(":").map(Number);
  return (isFinite(m) ? m * 60 : 0) + (isFinite(s) ? s : 0);
}

function fmt(total: number): string {
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export function LiveTimer({
  start,
  className = "",
}: {
  start: string;
  className?: string;
}) {
  const initial = parse(start);
  const [seconds, setSeconds] = useState(initial);

  useEffect(() => {
    const t0 = Date.now();
    const id = setInterval(() => {
      setSeconds(initial + Math.floor((Date.now() - t0) / 1000));
    }, 1000);
    return () => clearInterval(id);
  }, [initial]);

  return <span className={`tnum ${className}`}>{fmt(seconds)}</span>;
}
