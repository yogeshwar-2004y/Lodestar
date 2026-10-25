"use client";

import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";

import { http } from "@/lib/api";

export type Session = {
  user: { id: string; email: string; name: string };
  organization: { id: string; name: string; kind: string; kill_switch: boolean; is_demo: boolean; branding: Record<string, string> } | null;
  role: string | null;
  permissions: string[];
  memberships: { organization: { id: string; name: string; kind: string }; role: string }[];
  csrf_token: string;
};

export type Site = {
  id: string;
  workspace_id: string | null;
  name: string;
  domain: string;
  base_url: string;
  platform: string;
  status: string;
  verified_at: string | null;
  verification_method: string | null;
  crawl_settings: Record<string, unknown>;
  health_score: number | null;
  health_breakdown: { categories?: Record<string, number>; penalties?: { rule: string; points: number; affected: number }[]; methodology?: string; label?: string };
  last_crawl_at: string | null;
  business_goals: string | null;
  is_demo: boolean;
  created_at: string;
};

export function useSession() {
  return useQuery({ queryKey: ["session"], queryFn: () => http<Session>("/auth/me"), retry: false });
}

export function useCan(permission: string) {
  const { data } = useSession();
  return !!data?.permissions.includes(permission);
}

export function useSites() {
  return useQuery({ queryKey: ["sites"], queryFn: () => http<Site[]>("/sites") });
}

export function useSiteId() {
  const p = useParams<{ siteId?: string }>();
  return p?.siteId;
}

export function useSite(siteId?: string) {
  return useQuery({ queryKey: ["site", siteId], queryFn: () => http<Site>(`/sites/${siteId}`), enabled: !!siteId });
}

export function useMeta() {
  return useQuery({
    queryKey: ["meta"],
    queryFn: () => http<{ product_name: string; demo_mode: boolean; ai_mode: string; ai_model: string | null; ai_note: string | null; environment: string; integrations: Record<string, boolean> }>("/meta"),
    staleTime: 300_000,
  });
}
