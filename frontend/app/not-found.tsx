import Link from "next/link";
import { ArrowRight } from "lucide-react";

const PLACES: [string, string, string][] = [
  ["/forecasts", "Latest forecast", "The Week-2 rainfall outlook and its maps"],
  [
    "/monitoring",
    "Rainfall monitoring",
    "Observed rainfall of the latest dekad",
  ],
  ["/bulletin", "Weekly bulletin", "The bulletin of the current forecast"],
  ["/copilot", "Forecaster Copilot", "Ask about the forecast in plain words"],
];

export default function NotFound() {
  return (
    <div className="page">
      <div className="wrap not-found">
        <h2 className="section-title left">This page does not exist</h2>
        <p className="section-sub left">
          The address may be mistyped, or the page has moved. These are the
          places most people look for:
        </p>
        <div className="not-found-links">
          {PLACES.map(([href, title, text]) => (
            <Link key={href} href={href} className="not-found-link">
              <b>
                {title} <ArrowRight size={16} aria-hidden />
              </b>
              <span>{text}</span>
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}
