import { Compass } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { brand } from "@/lib/brand";

export function Logo({ className = "" }: { className?: string }) {
  return (
    <span className={`inline-flex items-center gap-2 font-semibold tracking-tight ${className}`}>
      <span className="grid size-7 place-items-center rounded-[9px] bg-gradient-to-br from-accent to-teal text-white shadow-sm">
        <Compass className="size-4" aria-hidden />
      </span>
      {brand.name}
    </span>
  );
}

export function MarketingNav() {
  return (
    <header className="sticky top-0 z-30 border-b border-border/60 bg-bg/80 backdrop-blur-md">
      <nav className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6" aria-label="Main">
        <Link href="/" aria-label={`${brand.name} home`}>
          <Logo />
        </Link>
        <div className="hidden items-center gap-7 text-sm text-fg-muted md:flex">
          <Link href="/#how" className="hover:text-fg">How it works</Link>
          <Link href="/#platforms" className="hover:text-fg">Platforms</Link>
          <Link href="/#safety" className="hover:text-fg">Safety</Link>
          <Link href="/pricing" className="hover:text-fg">Pricing</Link>
          <Link href="/#faq" className="hover:text-fg">FAQ</Link>
        </div>
        <div className="flex items-center gap-2">
          <Button asChild variant="ghost" size="sm">
            <Link href="/signin">Sign in</Link>
          </Button>
          <Button asChild size="sm">
            <Link href="/signup">Start free trial</Link>
          </Button>
        </div>
      </nav>
    </header>
  );
}

export function MarketingFooter() {
  return (
    <footer className="border-t border-border bg-bg-subtle/60">
      <div className="mx-auto grid max-w-6xl gap-10 px-4 py-12 sm:px-6 md:grid-cols-4">
        <div className="md:col-span-2">
          <Logo />
          <p className="mt-3 max-w-sm text-sm text-fg-muted">{brand.tagline}</p>
          <p className="mt-4 max-w-sm text-xs text-fg-subtle">
            {brand.name} does not guarantee rankings or traffic. Health scores are internal diagnostics, not Google metrics.
          </p>
        </div>
        <div className="text-sm">
          <p className="font-medium">Product</p>
          <ul className="mt-3 space-y-2 text-fg-muted">
            <li><Link href="/#how" className="hover:text-fg">How it works</Link></li>
            <li><Link href="/pricing" className="hover:text-fg">Pricing</Link></li>
            <li><Link href="/#safety" className="hover:text-fg">Security & approvals</Link></li>
          </ul>
        </div>
        <div className="text-sm">
          <p className="font-medium">Company</p>
          <ul className="mt-3 space-y-2 text-fg-muted">
            <li><a href={`mailto:${brand.supportEmail}`} className="hover:text-fg">Contact</a></li>
            <li><Link href="/signin" className="hover:text-fg">Sign in</Link></li>
          </ul>
        </div>
      </div>
      <div className="border-t border-border py-5 text-center text-xs text-fg-subtle">© {new Date().getFullYear()} {brand.name}. All rights reserved.</div>
    </footer>
  );
}
