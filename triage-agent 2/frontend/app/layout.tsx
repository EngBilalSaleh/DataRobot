import type { Metadata } from "next";
import "./globals.css";
import { Header } from "./header";

export const metadata: Metadata = {
  title: "Triage desk",
  description: "Customer support ticket triage agent: CrewAI Flows and RAG",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Sans+Arabic:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap"
        />
      </head>
      <body>
        <Header />
        {children}
      </body>
    </html>
  );
}
