import createClient from "openapi-fetch";
import type { components, paths } from "@contracts/schema";

export type Schemas = components["schemas"];

function csrfToken(): string | undefined {
  if (typeof document === "undefined") return undefined;
  return document.cookie
    .split("; ")
    .find((c) => c.startsWith("ls_csrf="))
    ?.split("=")[1];
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: unknown,
  ) {
    super(message);
  }
}

/** Typed client generated from the FastAPI OpenAPI document (packages/contracts). */
export const api = createClient<paths>({ baseUrl: "" , credentials: "include" });
api.use({
  onRequest({ request }) {
    const t = csrfToken();
    if (t && request.method !== "GET") request.headers.set("X-CSRF-Token", t);
    return request;
  },
});

/** Small fetch helper for endpoints returning loosely-typed aggregates. */
export async function http<T = unknown>(path: string, init: RequestInit & { json?: unknown; idempotencyKey?: string } = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.json !== undefined) headers.set("content-type", "application/json");
  const method = (init.method ?? (init.json !== undefined ? "POST" : "GET")).toUpperCase();
  const t = csrfToken();
  if (t && method !== "GET") headers.set("X-CSRF-Token", t);
  if (init.idempotencyKey) headers.set("Idempotency-Key", init.idempotencyKey);
  const res = await fetch(`/api/v1${path}`, {
    ...init,
    method,
    headers,
    credentials: "include",
    body: init.json !== undefined ? JSON.stringify(init.json) : init.body,
  });
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const e = body?.error ?? {};
    throw new ApiError(res.status, e.code ?? "error", e.message ?? `Request failed (${res.status})`, e.details);
  }
  return body as T;
}

export function newIdempotencyKey(prefix = "ui"): string {
  return `${prefix}-${crypto.randomUUID()}`;
}
