"use client";
/**
 * About this service: what it is for, what it does each week and where its data come from.
 */
import Link from "next/link";
import { Card, PageBanner } from "@/components/ui";

const STEPS = [
  [
    "Forecast",
    "Each week the ECMWF ensemble is downloaded and its Week-2 rainfall (days 8–14) is corrected with a monthly bias correction (MBC) and a CatBoost machine-learning model trained on ECMWF reforecasts, 2005–2021.",
  ],
  [
    "Verify",
    "Every forecast is scored against CHIRPS once the week has passed, and compared with TAMSAT, ARC 2.0, RFE 2.0 and GPM IMERG.",
  ],
  [
    "Communicate",
    "The weekly bulletin is drafted for the forecasters to check, edit and translate, then reviewed, approved and published.",
  ],
  [
    "Explain",
    "The Forecaster Copilot answers questions about the forecast, observed rainfall and verification, in the region's languages.",
  ],
] as const;

const WORK = [
  "Data preprocessing of historical weather data, reanalysis products and operational forecasts",
  "Exploratory analysis of rainfall and its climate drivers",
  "Development and evaluation of AI-based prediction models",
  "Identification of the most important climate drivers",
  "Assessment of forecast skill against observations",
];

const SECTORS = [
  "Agriculture",
  "Water resources",
  "Disaster risk management",
  "Food security",
];

export default function About() {
  return (
    <div className="page">
      <div className="wrap">
        <PageBanner
          title="About this service"
          crumbs={[{ label: "About" }]}
          subtitle="Application of Artificial Intelligence and Machine Learning for Medium-Range Prediction in Eastern Africa."
        />
        <Card title="Purpose">
          <p>
            This service explores how artificial intelligence (AI) and machine
            learning (ML) can improve medium-range forecasts, 7 to 14 days
            ahead, over Eastern Africa. It works with historical weather data,
            reanalysis products and operational forecast data to find out how AI
            and ML methods can complement dynamical forecasting systems such as
            the ECMWF ensemble.
          </p>
          <p style={{ marginBottom: 0 }}>
            The aim is to strengthen early warning systems and climate services
            for the sectors most sensitive to rainfall:{" "}
            {SECTORS.join(", ").toLowerCase()}.
          </p>
        </Card>
        <Card title="What it does each week">
          <ol className="about-steps">
            {STEPS.map(([title, text]) => (
              <li key={title}>
                <b>{title}</b>
                <span>{text}</span>
              </li>
            ))}
          </ol>
        </Card>
        <div className="about-grid">
          <Card title="The work behind it">
            <ul className="about-list">
              {WORK.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </Card>
          <Card title="Status">
            <p>
              The AI/ML forecasts are under evaluation: their scores are
              published on the <Link href="/verification">Verification</Link>{" "}
              page as each week is verified. ICPAC&apos;s official forecasts and
              bulletins are on{" "}
              <a
                href="https://www.icpac.net/weekly-forecast/"
                target="_blank"
                rel="noreferrer"
              >
                icpac.net
              </a>
              .
            </p>
            <p style={{ marginBottom: 0 }}>
              Data: ECMWF Open Data (CC BY 4.0); observations from CHIRPS,
              TAMSAT, ARC 2.0, RFE 2.0 and GPM IMERG.
            </p>
          </Card>
        </div>
      </div>
    </div>
  );
}
