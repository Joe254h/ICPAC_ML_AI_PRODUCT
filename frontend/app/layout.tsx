import type { Metadata } from "next";
import "./globals.css";
import "maplibre-gl/dist/maplibre-gl.css";
export const metadata: Metadata = { title: "ICPAC · Climate Intelligence", description: "Synthetic climate operations prototype" };
export default function Layout({ children }: Readonly<{ children: React.ReactNode }>) { return <html lang="en"><body>{children}</body></html>; }
