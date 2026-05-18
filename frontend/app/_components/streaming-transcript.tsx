"use client";

import { useEffect, useRef, useState } from "react";
import type { TranscriptLine } from "../_data/mock";

type Props = {
  transcript: TranscriptLine[];
  callerName: string;
  paralegalName: string;
  /**
   * How fast to advance the transcript. Lines reveal when the simulated call
   * time catches their timestamp.  1.0 = real-time, 4.0 = 4x speed.
   */
  speed?: number;
  /** Start automatically (default) or wait for a click. */
  autoStart?: boolean;
};

function parseTs(mmss: string): number {
  const [m, s] = mmss.split(":").map(Number);
  return (isFinite(m) ? m * 60 : 0) + (isFinite(s) ? s : 0);
}

export function StreamingTranscript({
  transcript,
  callerName,
  paralegalName,
  speed = 4,
  autoStart = true,
}: Props) {
  const [revealedCount, setRevealedCount] = useState(autoStart ? 1 : 0);
  const [running, setRunning] = useState(autoStart);
  const startRef = useRef<number | null>(autoStart ? Date.now() : null);
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!running) return;
    if (revealedCount >= transcript.length) return;
    const id = setInterval(() => {
      const start = startRef.current ?? Date.now();
      const elapsedRealS = (Date.now() - start) / 1000;
      const elapsedCallS = elapsedRealS * speed;
      let next = 0;
      for (let i = 0; i < transcript.length; i++) {
        const ts = parseTs(transcript[i].t);
        if (ts <= elapsedCallS) next = i + 1;
        else break;
      }
      setRevealedCount((c) => (next > c ? next : c));
    }, 250);
    return () => clearInterval(id);
  }, [running, transcript, speed, revealedCount]);

  // Auto-scroll the latest line into view as the transcript grows
  useEffect(() => {
    if (!containerRef.current) return;
    const last = containerRef.current.querySelector<HTMLDivElement>(
      "[data-transcript-line]:last-of-type",
    );
    last?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [revealedCount]);

  const start = () => {
    if (running) return;
    startRef.current = Date.now();
    setRevealedCount(1);
    setRunning(true);
  };

  const restart = () => {
    startRef.current = Date.now();
    setRevealedCount(1);
    setRunning(true);
  };

  const visible = transcript.slice(0, revealedCount);
  const done = revealedCount >= transcript.length;

  return (
    <div
      ref={containerRef}
      className="px-8 py-6 space-y-4 overflow-y-auto h-full"
    >
      {!running && (
        <div className="flex items-center justify-between px-4 py-3 rounded-lg glass-inset text-[12px]">
          <span className="text-white/70">
            Press start to stream the call transcript at {speed}×.
          </span>
          <button
            onClick={start}
            className="bg-white text-black text-[12px] font-medium px-3 py-1.5 rounded-md hover:bg-white/90"
          >
            Start stream
          </button>
        </div>
      )}

      {visible.map((line, i) => (
        <div key={i} data-transcript-line className="flex gap-4">
          <div className="w-10 shrink-0 text-[11px] text-soft tnum mono pt-0.5">
            {line.t}
          </div>
          <div className="flex-1">
            <div className="text-[11px] font-medium text-muted">
              {line.speaker === "Paralegal" ? paralegalName : callerName}
            </div>
            <div className="text-[14px] leading-snug mt-0.5 text-white">
              {line.text}
            </div>
          </div>
        </div>
      ))}

      {running && !done && (
        <div className="flex gap-4">
          <div className="w-10 shrink-0" />
          <div className="flex-1 flex items-center gap-2 text-[12px] text-muted italic">
            <span className="live-dot" />
            transcribing…
          </div>
        </div>
      )}

      {done && (
        <div className="flex gap-4 pt-2">
          <div className="w-10 shrink-0" />
          <div className="flex-1 flex items-center justify-between text-[12px]">
            <span className="text-muted italic">
              Call ended · full conversation above.
            </span>
            <button
              onClick={restart}
              className="text-white/80 hover:text-white text-[11px] underline"
            >
              Restart
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
