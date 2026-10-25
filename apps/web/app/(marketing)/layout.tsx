import { MarketingFooter, MarketingNav } from "@/components/marketing/chrome";

export default function MarketingLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <MarketingNav />
      <main id="main">{children}</main>
      <MarketingFooter />
    </>
  );
}
