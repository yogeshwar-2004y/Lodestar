import Link from "next/link";

export default function NotFound() {
  return (
    <main id="main" className="grid min-h-dvh place-items-center px-4 text-center">
      <div>
        <p className="font-display text-7xl">404</p>
        <p className="mt-2 text-fg-muted">This page doesn&apos;t exist, or you don&apos;t have access to it.</p>
        <Link href="/app" className="mt-6 inline-block text-accent hover:underline">Back to the app</Link>
      </div>
    </main>
  );
}
