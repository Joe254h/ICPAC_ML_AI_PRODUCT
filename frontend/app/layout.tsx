import type { Metadata } from "next";
import "./globals.css";
import "maplibre-gl/dist/maplibre-gl.css";
import Shell from "@/components/shell";

export const metadata: Metadata = {
  title: {
    default: "Week-2 Rainfall Forecasts | ICPAC",
    template: "%s | ICPAC Week-2 Forecasts",
  },
  description:
    "Week-2 (days 8-14) rainfall forecasts for Eastern Africa from the IGAD Climate " +
    "Prediction and Applications Centre: the ECMWF ensemble with bias correction, " +
    "verified against CHIRPS.",
};

export default function Layout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" data-scroll-behavior="smooth">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          rel="preconnect"
          href="https://fonts.gstatic.com"
          crossOrigin="anonymous"
        />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Open+Sans:wght@400;600;700&display=swap"
        />
      </head>
      <body>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
