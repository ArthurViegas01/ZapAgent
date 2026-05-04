"use client";

import { useEffect, useRef, useState } from "react";
import { usePathname, useSearchParams } from "next/navigation";

export function TopProgressBar() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [progress, setProgress] = useState(0);
  const [visible, setVisible] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const doneRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (intervalRef.current) clearInterval(intervalRef.current);
    if (doneRef.current) clearTimeout(doneRef.current);

    setVisible(true);
    setProgress(15);

    intervalRef.current = setInterval(() => {
      setProgress((p) => {
        if (p >= 80) { clearInterval(intervalRef.current!); return p; }
        return p + Math.random() * 15;
      });
    }, 150);

    doneRef.current = setTimeout(() => {
      clearInterval(intervalRef.current!);
      setProgress(100);
      setTimeout(() => { setVisible(false); setProgress(0); }, 300);
    }, 350);

    return () => {
      clearInterval(intervalRef.current!);
      clearTimeout(doneRef.current!);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname, searchParams?.toString()]);

  if (!visible && progress === 0) return null;

  return (
    <div
      className="pointer-events-none fixed left-0 top-0 z-[9999] h-[2px] bg-brand-600"
      style={{
        width: `${progress}%`,
        opacity: visible ? 1 : 0,
        transition: progress === 100
          ? "width 150ms ease, opacity 300ms ease 150ms"
          : "width 200ms ease",
      }}
    />
  );
}
