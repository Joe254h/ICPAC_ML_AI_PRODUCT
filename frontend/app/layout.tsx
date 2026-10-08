import type { Metadata } from "next";
import "./globals.css";
import "maplibre-gl/dist/maplibre-gl.css";
import Shell from "@/components/shell";

export const metadata: Metadata = {
  title: { default: "ICPAC Climate AI", template: "%s · ICPAC Climate AI" },
  description:
    "Week-2 rainfall forecasts for the ICPAC region: raw ECMWF, MBC and MBC + Atmos37 CatBoost",
};

// Applies the saved theme before the first paint, so dark mode never flashes.
const theme = `try{if(localStorage.getItem("icpac-theme")==="dark")document.documentElement.classList.add("dark")}catch(e){}`;

export default function Layout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: theme }} />
      </head>
      <body>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
