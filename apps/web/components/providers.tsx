"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import * as React from "react";
import { Toaster } from "sonner";

import { ApiError } from "@/lib/api";

type Theme = "light" | "dark" | "system";
const ThemeCtx = React.createContext<{ theme: Theme; setTheme: (t: Theme) => void }>({ theme: "system", setTheme: () => {} });
export const useTheme = () => React.useContext(ThemeCtx);

function applyTheme(t: Theme) {
  const dark = t === "dark" || (t === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
}

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = React.useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 15_000,
            refetchOnWindowFocus: false,
            retry: (count, err) => !(err instanceof ApiError && [401, 403, 404].includes(err.status)) && count < 2,
          },
        },
      }),
  );
  const [theme, setThemeState] = React.useState<Theme>("system");
  React.useEffect(() => {
    let saved: Theme = "system";
    try {
      saved = (localStorage.getItem("ls-theme") as Theme) || "system";
    } catch {}
    setThemeState(saved);
    applyTheme(saved);
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => applyTheme((localStorage.getItem("ls-theme") as Theme) || "system");
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  const setTheme = React.useCallback((t: Theme) => {
    setThemeState(t);
    try {
      localStorage.setItem("ls-theme", t);
    } catch {}
    applyTheme(t);
  }, []);
  return (
    <ThemeCtx.Provider value={{ theme, setTheme }}>
      <QueryClientProvider client={client}>
        {children}
        <Toaster position="bottom-right" richColors closeButton toastOptions={{ style: { fontFamily: "var(--font-sans)" } }} />
      </QueryClientProvider>
    </ThemeCtx.Provider>
  );
}
