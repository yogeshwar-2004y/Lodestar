"use client";

import { useRouter } from "next/navigation";
import * as React from "react";

import { Skeleton } from "@/components/ui/core";
import { useSites } from "@/lib/hooks";

export default function AppHome() {
  const router = useRouter();
  const { data } = useSites();
  React.useEffect(() => {
    if (!data) return;
    let stored: string | null = null;
    try {
      stored = localStorage.getItem("ls-site");
    } catch {}
    const target = data.find((s) => s.id === stored) ?? data[0];
    router.replace(target ? `/app/sites/${target.id}` : "/app/sites/new");
  }, [data, router]);
  return <Skeleton className="h-40 w-full" />;
}
