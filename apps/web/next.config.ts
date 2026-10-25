import type { NextConfig } from "next";

const rawApi = process.env.API_INTERNAL_URL ?? "http://localhost:8400";
// Accept a bare host (e.g. Render's fromService.host) and assume HTTPS.
const API = rawApi.includes("://") ? rawApi : `https://${rawApi}`;

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // Same-origin API: the browser talks to /api/v1 and Next proxies to FastAPI, so the
  // session cookie stays first-party (SameSite=Lax) and CSRF uses a double-submit header.
  async rewrites() {
    return [{ source: "/api/v1/:path*", destination: `${API}/api/v1/:path*` }];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        ],
      },
    ];
  },
};

export default nextConfig;
