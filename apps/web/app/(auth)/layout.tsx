import Link from "next/link";

import { Logo } from "@/components/marketing/chrome";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="relative grid min-h-dvh place-items-center overflow-hidden px-4 py-10">
      <div className="bg-grid pointer-events-none absolute inset-0 opacity-30 [mask-image:radial-gradient(ellipse_at_center,black_20%,transparent_70%)]" aria-hidden />
      <main id="main" className="relative w-full max-w-md">
        <Link href="/" className="mb-8 flex justify-center">
          <Logo className="text-lg" />
        </Link>
        <div className="rounded-2xl border border-border bg-surface p-7 shadow-xl">{children}</div>
      </main>
    </div>
  );
}
