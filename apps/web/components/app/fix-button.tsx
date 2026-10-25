"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Wand2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { ApiError, http, newIdempotencyKey } from "@/lib/api";
import { useCan } from "@/lib/hooks";

/** Asks the Execution Agent to draft an immutable patch for one page, then opens it. */
export function FixButton({ siteId, url, action, findingId, size = "sm", label = "Draft fix" }: { siteId: string; url: string; action: string; findingId?: string; size?: "sm" | "md"; label?: string }) {
  const router = useRouter();
  const qc = useQueryClient();
  const can = useCan("change:propose");
  const m = useMutation({
    mutationFn: () =>
      http<{ id: string; status: string }>("/change-sets", {
        json: { site_id: siteId, url, action_type: action, finding_id: findingId },
        idempotencyKey: newIdempotencyKey("propose"),
      }),
    onSuccess: (cs) => {
      qc.invalidateQueries({ queryKey: ["changes"] });
      toast.success(cs.status === "recommendation" ? "Recommendation created (no connector can write this)" : "Patch drafted — review it");
      router.push(`/app/fixes/${cs.id}`);
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not draft a fix"),
  });
  if (!can || !["meta_description", "title"].includes(action)) return null;
  return (
    <Button size={size} variant="secondary" onClick={(e) => { e.stopPropagation(); m.mutate(); }} loading={m.isPending}>
      <Wand2 /> {label}
    </Button>
  );
}
