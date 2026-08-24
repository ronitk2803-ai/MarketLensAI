import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

import { AppHeader } from "@/components/domain/AppHeader";
import { ThemeScript } from "@/components/domain/ThemeToggle";
import { TooltipProvider } from "@/components/ui/tooltip";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "MarketLens AI — Investment Intelligence",
  description: "Discover and stress-test investment opportunities with evidence, not opinions.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <head>
        <ThemeScript />
      </head>
      <body className="flex min-h-full flex-col">
        <TooltipProvider delayDuration={150}>
          <AppHeader />
          {children}
          <footer className="mt-auto border-t border-border px-4 py-3">
            <p className="mx-auto max-w-[1600px] text-[11px] leading-relaxed text-muted-foreground">
              Research tooling, not investment advice. Scores describe research
              attractiveness — never a predicted return or a buy/sell recommendation. Data is
              end-of-day and may be delayed or incomplete; every figure carries its own source
              and timestamp.
            </p>
          </footer>
        </TooltipProvider>
      </body>
    </html>
  );
}
