/*
 * The project deck: the full Week-2 experiment, the web service, what comes next and how a
 * data scientist can help ICPAC. Every figure is copied from the frozen verification tables
 * under artifacts/verification (see the notes of each slide for the file).
 *
 *   NODE_PATH=<folder with pptxgenjs, react, react-dom, react-icons, sharp> \
 *     node docs/presentation/build_deck.js docs/presentation/ICPAC_Week2_ML_Project.pptx
 *
 * Then apply the theme colours (the pptx skill's apply_theme.js) as the script does at the
 * end when APPLY_THEME points to it.
 */
const path = require("path");
const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const fa = require("react-icons/fa6");

const OUT = process.argv[2] || path.join(__dirname, "ICPAC_Week2_ML_Project.pptx");
const SCREENS = path.join(__dirname, "screens");

const THEME = {
  name: "ICPAC Forest",
  headFontFace: "Cambria",
  bodyFontFace: "Calibri",
  colors: {
    dk1: "17211B",
    lt1: "FFFFFF",
    dk2: "0A3321",
    lt2: "EEF6F1",
    accent1: "125D3B",
    accent2: "E5A10F",
    accent3: "2A78D6",
    accent4: "E0802F",
    accent5: "1BAF7A",
    accent6: "646B65",
    hlink: "1F62A8",
    folHlink: "6D2E46",
  },
};
const HEX = {
  ink: "17211B",
  deep: "0A3321",
  forest: "125D3B",
  pale: "EEF6F1",
  amber: "E5A10F",
  raw: "2A78D6",
  mbc: "E0802F",
  hybrid: "1BAF7A",
  clim: "9AA19B",
  muted: "646B65",
  line: "DDE3DE",
  white: "FFFFFF",
};

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.33 x 7.5 in
pres.title = "ICPAC Week-2 rainfall: machine learning and the web service";
pres.author = "ICPAC internship";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
const C = pres.SchemeColor;

// ------------------------------------------------------------------ layouts
const FOOTER = "ICPAC Week-2 rainfall outlook · ML experiment and web service";
pres.defineSlideMaster({
  title: "TITLE_DARK",
  background: { color: HEX.deep },
  objects: [
    {
      placeholder: {
        options: { name: "title", type: "title", x: 0.8, y: 2.0, w: 11.7, h: 1.9, fontSize: 44, bold: true, color: C.background1, valign: "bottom", align: "left" },
        text: "Title",
      },
    },
    {
      placeholder: {
        options: { name: "body", type: "body", x: 0.8, y: 4.1, w: 11.7, h: 1.6, fontSize: 20, color: C.background2, valign: "top" },
        text: "Subtitle",
      },
    },
  ],
});
pres.defineSlideMaster({
  title: "SECTION",
  background: { color: HEX.forest },
  objects: [
    {
      placeholder: {
        options: { name: "title", type: "title", x: 0.8, y: 2.6, w: 11.7, h: 1.3, fontSize: 40, bold: true, color: C.background1, valign: "bottom", align: "left" },
        text: "Section",
      },
    },
    {
      placeholder: {
        options: { name: "body", type: "body", x: 0.8, y: 4.0, w: 11.7, h: 1.2, fontSize: 20, color: C.background2, valign: "top" },
        text: "What this section covers",
      },
    },
  ],
  slideNumber: { x: 12.3, y: 6.95, w: 0.6, h: 0.3, fontSize: 10, color: C.background2, align: "right" },
});
pres.defineSlideMaster({
  title: "CONTENT",
  background: { color: HEX.white },
  margin: [0.5, 0.6, 0.7, 0.6],
  objects: [
    {
      placeholder: {
        options: { name: "title", type: "title", x: 0.6, y: 0.35, w: 12.1, h: 0.85, fontSize: 34, bold: true, color: C.text2, valign: "middle", margin: 0 },
        text: "Slide title",
      },
    },
    { text: { text: FOOTER, options: { x: 0.6, y: 6.95, w: 9, h: 0.3, fontSize: 10, color: C.accent6, margin: 0 } } },
  ],
  slideNumber: { x: 12.1, y: 6.95, w: 0.6, h: 0.3, fontSize: 10, color: C.accent6, align: "right" },
});

// ------------------------------------------------------------------ helpers
async function icon(Component, color = "#FFFFFF") {
  const svg = ReactDOMServer.renderToStaticMarkup(React.createElement(Component, { color, size: "256" }));
  const png = await sharp(Buffer.from(svg)).resize(256, 256).png().toBuffer();
  return "image/png;base64," + png.toString("base64");
}

function content(section) {
  return pres.addSlide({ masterName: "CONTENT", sectionTitle: section });
}

function card(slide, x, y, w, h, name, fill = HEX.pale) {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x, y, w, h, rectRadius: 0.12, fill: { color: fill }, line: { color: fill }, objectName: name,
  });
}

async function iconCard(slide, x, y, w, h, Ico, head, body, name, opts = {}) {
  card(slide, x, y, w, h, name + " card", opts.fill || HEX.pale);
  slide.addShape(pres.shapes.OVAL, { x: x + 0.25, y: y + 0.25, w: 0.6, h: 0.6, fill: { color: opts.dot || HEX.forest }, line: { color: opts.dot || HEX.forest }, objectName: name + " icon circle" });
  slide.addImage({ data: await icon(Ico), x: x + 0.39, y: y + 0.39, w: 0.32, h: 0.32, altText: head });
  slide.addText(head, { x: x + 1.0, y: y + 0.22, w: w - 1.2, h: 0.66, fontSize: 17, bold: true, color: C.text2, valign: "middle", margin: 0, isTextBox: true, objectName: name + " heading" });
  slide.addText(body, { x: x + 0.25, y: y + 1.0, w: w - 0.5, h: h - 1.15, fontSize: 15, color: C.text1, valign: "top", margin: 0, isTextBox: true, objectName: name + " text", paraSpaceAfter: 4 });
}

function stat(slide, x, y, w, value, label, name, color = C.accent1) {
  slide.addText(value, { x, y, w, h: 1.0, fontSize: 54, bold: true, color, fontFace: THEME.headFontFace, margin: 0, valign: "bottom", isTextBox: true, objectName: name + " value" });
  slide.addText(label, { x, y: y + 1.05, w, h: 0.75, fontSize: 14, color: C.text1, margin: 0, valign: "top", isTextBox: true, objectName: name + " label" });
}

function bullets(items, size = 16) {
  return items.map((t, i) => ({ text: t, options: { bullet: true, breakLine: i < items.length - 1, fontSize: size, paraSpaceAfter: 8 } }));
}

const CHART_TEXT = { catAxisLabelFontFace: "+mn-lt", valAxisLabelFontFace: "+mn-lt", dataLabelFontFace: "+mn-lt", titleFontFace: "+mn-lt", legendFontFace: "+mn-lt" };
function chartBase(title) {
  return {
    ...CHART_TEXT,
    showTitle: true, title, titleFontSize: 14, titleColor: HEX.ink,
    catAxisLabelColor: HEX.muted, valAxisLabelColor: HEX.muted, catAxisLabelFontSize: 12, valAxisLabelFontSize: 11,
    dataLabelFontSize: 11, dataLabelColor: HEX.ink,
    valGridLine: { color: HEX.line, size: 0.5 }, catGridLine: { style: "none" },
    legendFontSize: 12, legendColor: HEX.ink,
  };
}

function screen(slide, file, x, y, w, alt, name) {
  const h = (w * 900) / 1440;
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: x - 0.04, y: y - 0.04, w: w + 0.08, h: h + 0.08, rectRadius: 0.06, fill: { color: HEX.line }, line: { color: HEX.line }, shadow: { type: "outer", color: "000000", opacity: 0.18, blur: 8, offset: 3, angle: 90 }, objectName: name + " frame" });
  slide.addImage({ path: path.join(SCREENS, file), x, y, w, h, altText: alt, objectName: name });
  return h;
}

// ------------------------------------------------------------------ slides
async function build() {
  // 1. Title
  pres.addSection({ title: "Opening" });
  let s = pres.addSlide({ masterName: "TITLE_DARK", sectionTitle: "Opening" });
  s.addText("Machine learning for Week-2 rainfall in Eastern Africa", { placeholder: "title" });
  s.addText(
    [
      { text: "An MBC + CatBoost residual hybrid on ECMWF ensemble forecasts, and the ICPAC Week-2 Rainfall Outlook service built around it", options: { breakLine: true } },
      { text: "Sangura J. Nyongesa · ICPAC internship · Supervisor: Dr. Masilin Gudoshava", options: { fontSize: 16, color: C.accent2 } },
    ],
    { placeholder: "body" },
  );
  s.addNotes("Introduce the two parts of the work: the scientific experiment (can machine learning improve ECMWF's Week-2 rainfall over the 11 ICPAC member states?) and the operational web service that issues that forecast every week. Close with next steps.");

  // 2. The message
  s = content("Opening");
  s.addText("The short answer", { placeholder: "title" });
  stat(s, 0.6, 1.5, 3.8, "12.2%", "lower RMSE than raw ECMWF Week-2 rainfall (17.27 to 15.16 mm/week)", "stat raw", C.accent1);
  stat(s, 4.75, 1.5, 3.8, "1.4%", "further gain of the CatBoost correction over bias correction (MBC) alone", "stat mbc", C.accent4);
  stat(s, 8.9, 1.5, 3.8, "Weekly", "forecast, maps, bulletin, Copilot and verification issued by one web service", "stat service", C.text2);
  card(s, 0.6, 4.25, 12.1, 2.35, "message card");
  s.addText(
    [
      { text: "What this means. ", options: { bold: true, color: C.text2 } },
      { text: "Most of the skill over raw ECMWF comes from multiplicative bias correction (MBC). The machine learning layer adds a small, consistent improvement on top, largest in June to September and in the drier north. Both are now issued operationally, with every figure checked and every forecast verified against CHIRPS and three other rainfall datasets once the week has passed.", options: { color: C.text1 } },
    ],
    { x: 0.95, y: 4.45, w: 11.4, h: 1.95, fontSize: 17, valign: "middle", margin: 0, isTextBox: true, objectName: "message text" },
  );
  s.addNotes("Figures: refit retrospective 2022-2024, artifacts/verification/FINAL_REFIT_RETROSPECTIVE_2022_2024_20261027/tables/GLOBAL_METRICS.csv. CatBoost 15.156, MBC 15.364, raw ECMWF 17.269 mm/week. 12.2% = 1 - 15.156/17.269; 1.4% = 1 - 15.156/15.364. The pre-refit independent test gives the same picture (15.204 vs 15.416 vs 17.269).");

  // 3. Agenda
  s = content("Opening");
  s.addText("What I will cover", { placeholder: "title" });
  const agenda = [
    [fa.FaFlask, "The experiment", "Data, method, experimental design and results by region, season, month and country"],
    [fa.FaDesktop, "The web service", "How the forecast is issued every week: maps, bulletin, Copilot and verification"],
    [fa.FaRocket, "What comes next", "The most promising advances for Week-2 prediction at ICPAC"],
    [fa.FaHandshake, "How I can help ICPAC", "Where a data scientist adds value to ICPAC's operations and partners"],
  ];
  for (let i = 0; i < agenda.length; i++) {
    const [ico, head, body] = agenda[i];
    await iconCard(s, 0.6 + (i % 2) * 6.15, 1.5 + Math.floor(i / 2) * 2.6, 5.95, 2.35, ico, head, body, "agenda " + (i + 1));
  }

  // ---------------------------------------------------------------- experiment
  pres.addSection({ title: "The experiment" });
  s = pres.addSlide({ masterName: "SECTION", sectionTitle: "The experiment" });
  s.addText("Part 1. The experiment", { placeholder: "title" });
  s.addText("Can machine learning improve ECMWF's Week-2 rainfall over the 11 ICPAC member states?", { placeholder: "body" });

  // 5. Problem and data
  s = content("The experiment");
  s.addText("Question and data", { placeholder: "title" });
  s.addText(
    [
      { text: "Week-2 (days 8-14) is the gap between weather forecasts and monthly outlooks, and the week farmers, water managers and disaster officers plan around.", options: { breakLine: true, paraSpaceAfter: 10 } },
      { text: "Raw ECMWF ensemble rainfall is too wet over the region on average (bias +1.63 mm/week) and loses skill in June to September.", options: { breakLine: true, paraSpaceAfter: 10 } },
      { text: "The goal: correct it cell by cell on ICPAC's 0.05° grid, and check honestly whether machine learning adds anything beyond bias correction.", options: {} },
    ],
    { x: 0.6, y: 1.5, w: 5.6, h: 4.9, fontSize: 17, color: C.text1, valign: "top", margin: 0, isTextBox: true, objectName: "question text" },
  );
  const facts = [
    ["Forecasts", "ECMWF S2S reforecasts, model version 2025, 10 members"],
    ["Years", "Hindcasts 2005-2024, an initialisation every two days"],
    ["Truth", "CHIRPS v2.0 Week-2 totals, 0.05°"],
    ["Domain", "11 member states, 800 × 700 grid cells"],
    ["Training", "3,148 cases, 647 million cell rows (2005-2021)"],
    ["Scoring", "551 cases, 113 million cell rows (2022-2024)"],
  ];
  s.addTable(
    facts.map(([a, b]) => [
      { text: a, options: { bold: true, color: HEX.deep, fill: { color: HEX.pale } } },
      { text: b, options: { color: HEX.ink } },
    ]),
    { x: 6.6, y: 1.5, w: 6.1, colW: [1.5, 4.6], fontSize: 15, rowH: 0.72, border: { type: "solid", pt: 0.75, color: HEX.line }, valign: "middle", margin: 0.08, objectName: "data table" },
  );
  s.addNotes("Bias +1.63 mm/week: raw ECMWF over 2022-2024, GLOBAL_METRICS.csv. Training rows and cases: provenance/README_FIRST.txt of the refit retrospective.");

  // 6. Method
  s = content("The experiment");
  s.addText("Method: bias correction, then a learned residual", { placeholder: "title" });
  const steps = [
    ["Raw ECMWF", "Ensemble mean and spread of Week-2 rainfall, regridded to 0.05°", HEX.raw],
    ["MBC", "Multiplicative bias correction: observed / forecast mean ratio per cell and initialisation month", HEX.mbc],
    ["24 predictors", "Rainfall mean and spread, MBC, place, season, 17 atmospheric PCs", HEX.forest],
    ["CatBoost", "Learns the remaining error (residual) of MBC from the 24 predictors", HEX.hybrid],
    ["Final rainfall", "max(MBC + residual, 0): never negative, never filled in", HEX.deep],
  ];
  const sw = 2.2, gap = 0.27;
  for (let i = 0; i < steps.length; i++) {
    const x = 0.6 + i * (sw + gap);
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 1.7, w: sw, h: 0.95, rectRadius: 0.1, fill: { color: steps[i][2] }, line: { color: steps[i][2] }, objectName: "step " + (i + 1) + " box" });
    s.addText(steps[i][0], { x, y: 1.7, w: sw, h: 0.95, fontSize: 18, bold: true, color: C.background1, align: "center", valign: "middle", margin: 0, isTextBox: true, objectName: "step " + (i + 1) + " name" });
    s.addText(steps[i][1], { x, y: 2.8, w: sw, h: 1.5, fontSize: 14, color: C.text1, align: "left", valign: "top", margin: 0.05, isTextBox: true, objectName: "step " + (i + 1) + " text" });
    if (i < steps.length - 1) s.addText("›", { x: x + sw, y: 1.85, w: gap, h: 0.6, fontSize: 30, color: C.accent6, align: "center", margin: 0, isTextBox: true, objectName: "arrow " + (i + 1) });
  }
  card(s, 0.6, 4.6, 12.1, 1.95, "method note");
  s.addText(
    [
      { text: "Why a residual model. ", options: { bold: true, color: C.text2 } },
      { text: "Bias correction is simple and robust; asking CatBoost only for what MBC gets wrong keeps the physics-based forecast in charge and makes any gain from machine learning easy to measure. Gradient boosting (CatBoost) was chosen over LightGBM on validation scores; it handles hundreds of millions of rows on the HPC.", options: {} },
    ],
    { x: 0.95, y: 4.75, w: 11.4, h: 1.65, fontSize: 16, color: C.text1, valign: "middle", margin: 0, isTextBox: true, objectName: "method note text" },
  );
  s.addNotes("Formulas from climate_engine/models/hybrid7_pc17.py: residual = CatBoost(24 predictors); catboost_full = max(MBC + residual, 0). Validation 2020-2021 RMSE: CatBoost 14.280, LightGBM 14.383 (foundational_validation_independent_comparison.csv); independent test 15.204 vs 15.238. MBC ratio = clip(observed mean / forecast mean) per initialisation month and cell, 2005-2021 (climate_engine/operational/corrections.py).");

  // 7. Predictors
  s = content("The experiment");
  s.addText("The 24 predictors", { placeholder: "title" });
  const groups = [
    [fa.FaCloudRain, "Rainfall (3)", "Ensemble mean and spread of Week-2 rainfall, and the MBC-corrected value"],
    [fa.FaLocationDot, "Place and season (4)", "Latitude and longitude; day of year as sine and cosine"],
    [fa.FaWind, "Atmosphere (17)", "17 principal components of 15 upper-air quantities (humidity, winds, moisture flux, temperature, geopotential height, shear; 850-200 hPa), mean and spread"],
  ];
  for (let i = 0; i < groups.length; i++) {
    await iconCard(s, 0.6 + i * 4.1, 1.5, 3.9, 2.6, groups[i][0], groups[i][1], groups[i][2], "predictor group " + (i + 1));
  }
  s.addText(
    bullets([
      "PCA keeps the atmospheric information in 17 numbers per cell instead of 30 fields, fitted on training years only",
      "Every input has a fixed schema and checksum; the operational model refuses a forecast whose inputs differ",
      "A new predictor kit (124 candidate variables in 19 groups, with PCA/EOF reduction) is built for the HPC but not yet run",
    ], 15),
    { x: 0.6, y: 4.4, w: 12.1, h: 2.2, color: C.text1, valign: "top", margin: 0, isTextBox: true, objectName: "predictor notes" },
  );
  s.addNotes("Feature schema: artifacts/bundles/ICPAC_WEEK2_CATBOOST_FINAL_REFIT_2005_2021 (feature_schema). The predictor kit lives in training/predictors and has not been run on the HPC yet: no results from it are claimed.");

  // 8. Design
  s = content("The experiment");
  s.addText("Experimental design: two stages, stated honestly", { placeholder: "title" });
  const bars = [
    ["Pre-refit model", [["Train 2005-2019", 0, 15, HEX.forest], ["Validate\n2020-21", 15, 2, HEX.amber], ["Test\n2022-24", 17, 3, HEX.raw]]],
    ["Final refit", [["Train 2005-2021", 0, 17, HEX.forest], ["Retrospective\n2022-24", 17, 3, HEX.clim]]],
  ];
  const x0 = 2.6, yr = 10.1 / 20;
  bars.forEach(([label, parts], r) => {
    const y = 1.75 + r * 1.25;
    s.addText(label, { x: 0.6, y, w: 1.9, h: 0.75, fontSize: 15, bold: true, color: C.text2, valign: "middle", margin: 0, isTextBox: true, objectName: label + " label" });
    parts.forEach(([t, start, len, col]) => {
      s.addShape(pres.shapes.RECTANGLE, { x: x0 + start * yr, y, w: len * yr - 0.04, h: 0.75, fill: { color: col }, line: { color: HEX.white, width: 1 }, objectName: label + " " + t });
      s.addText(t, { x: x0 + start * yr, y, w: len * yr - 0.04, h: 0.75, fontSize: len < 4 ? 12 : 15, color: C.background1, bold: true, align: "center", valign: "middle", margin: 0.03, isTextBox: true, objectName: label + " " + t + " text" });
    });
  });
  s.addText(
    bullets([
      "Pre-refit: the policy was chosen on 2020-2021 and tested once on 2022-2024 (551 cases), never tuned on them",
      "Final refit: MBC, PCA and CatBoost refitted on all of 2005-2021 for operations; its 2022-2024 scores are post-selection, so they are a retrospective comparison, not a second independent test",
      "The full CatBoost correction became the web default after the independent scores were seen; that choice is descriptive",
    ], 15),
    { x: 0.6, y: 4.5, w: 12.1, h: 2.1, color: C.text1, valign: "top", margin: 0, isTextBox: true, objectName: "design notes" },
  );
  s.addNotes("Wording from backend/app/services/evidence.py scope statements and provenance/README_FIRST.txt: 'The 2022-2024 comparison is post-selection, not a new untouched independent test.'");

  // 9. Independent test
  s = content("The experiment");
  s.addText("Independent test, 2022-2024 (pre-refit models)", { placeholder: "title" });
  const pre = [["Raw ECMWF", 17.269], ["Climatology", 17.614], ["MBC", 15.416], ["MAM-protected", 15.271], ["LightGBM", 15.238], ["Blend α 0.75", 15.21], ["CatBoost", 15.204]];
  s.addChart(pres.charts.BAR, [{ name: "RMSE (mm/week)", labels: pre.map((r) => r[0]), values: pre.map((r) => r[1]) }], {
    ...chartBase("RMSE, mm/week (lower is better), 551 cases"),
    x: 0.6, y: 1.4, w: 7.4, h: 5.3, barDir: "bar", showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "0.00",
    valAxisMinVal: 14, valAxisMaxVal: 18, showLegend: false,
    chartColors: [HEX.raw, HEX.clim, HEX.mbc, HEX.hybrid, HEX.hybrid, HEX.hybrid, HEX.forest], invertedColors: [HEX.raw],
    objectName: "independent RMSE chart",
  });
  await iconCard(s, 8.4, 1.5, 4.3, 2.4, fa.FaCheck, "CatBoost lowest", "15.204 mm/week: 12.0% below raw ECMWF and 1.4% below MBC. Anomaly correlation 0.50 against 0.37 for raw ECMWF.", "independent best");
  await iconCard(s, 8.4, 4.15, 4.3, 2.4, fa.FaCircleInfo, "Read with care", "Every ML variant lands within 0.07 mm/week of the others. The step that matters most is MBC; the ML layer refines it.", "independent caution", { dot: HEX.amber });
  s.addNotes("Source: artifacts/verification/PRE_REFIT_INDEPENDENT_2022_2024_20261025/tables/T01_independent_regional_metrics.csv. The axis starts at 14 mm/week to show the differences; say so when presenting.");

  // 10. Refit retrospective
  s = content("The experiment");
  s.addText("Final refit, 2022-2024 retrospective", { placeholder: "title" });
  const refit = [["Raw ECMWF", 17.269, 0.366], ["Climatology", 17.519, null], ["MBC", 15.364, 0.479], ["CatBoost hybrid", 15.156, 0.498]];
  s.addChart(pres.charts.BAR, [{ name: "RMSE", labels: refit.map((r) => r[0]), values: refit.map((r) => r[1]) }], {
    ...chartBase("RMSE, mm/week (lower is better)"),
    x: 0.6, y: 1.4, w: 6.0, h: 5.2, barDir: "col", showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "0.00",
    valAxisMinVal: 14, valAxisMaxVal: 18, showLegend: false, chartColors: [HEX.raw, HEX.clim, HEX.mbc, HEX.hybrid],
    objectName: "refit RMSE chart",
  });
  const rows = [
    ["", "RMSE", "MAE", "Bias", "ACC"],
    ["CatBoost hybrid", "15.16", "7.53", "-0.27", "0.50"],
    ["MBC", "15.36", "7.67", "-0.26", "0.48"],
    ["Raw ECMWF", "17.27", "9.07", "+1.63", "0.37"],
    ["Climatology", "17.52", "8.74", "-1.33", "–"],
  ];
  s.addTable(
    rows.map((r, i) => r.map((v, j) => ({ text: v, options: { bold: i === 0 || j === 0, color: i === 0 ? HEX.white : HEX.ink, fill: { color: i === 0 ? HEX.forest : i === 1 ? HEX.pale : HEX.white }, align: j === 0 ? "left" : "right" } }))),
    { x: 7.0, y: 1.5, w: 5.7, colW: [2.1, 0.9, 0.9, 0.9, 0.9], fontSize: 14, rowH: 0.5, border: { type: "solid", pt: 0.75, color: HEX.line }, valign: "middle", margin: 0.08, objectName: "refit metrics table" },
  );
  s.addText(
    [
      { text: "mm/week; ACC = anomaly correlation. ", options: { color: C.accent6 } },
      { text: "Refit against the pre-refit model, same cases: CatBoost RMSE -0.048 mm/week, 95% interval -0.105 to +0.020 (monthly block bootstrap, exploratory). The refit is no worse, and not clearly better.", options: {} },
    ],
    { x: 7.0, y: 4.25, w: 5.7, h: 2.3, fontSize: 14, color: C.text1, valign: "top", margin: 0, isTextBox: true, objectName: "refit note" },
  );
  s.addNotes("Sources: FINAL_REFIT_RETROSPECTIVE_2022_2024_20261027/tables/GLOBAL_METRICS.csv and PAIRED_OLD_VS_REFIT_MONTH_BLOCK_CI.csv. Post-selection: 2022-2024 had been used to choose the policy.");

  // 11. Seasons
  s = content("The experiment");
  s.addText("Error by season", { placeholder: "title" });
  const seasons = ["DJF", "MAM", "JJA", "SON"];
  s.addChart(pres.charts.BAR, [
    { name: "Raw ECMWF", labels: seasons, values: [15.16, 18.73, 16.43, 18.39] },
    { name: "Climatology", labels: seasons, values: [16.78, 19.63, 13.4, 19.52] },
    { name: "MBC", labels: seasons, values: [14.56, 17.14, 13.09, 16.31] },
    { name: "CatBoost hybrid", labels: seasons, values: [14.39, 17.03, 12.53, 16.24] },
  ], {
    ...chartBase("RMSE by season, mm/week, 2022-2024 retrospective"),
    x: 0.6, y: 1.4, w: 7.8, h: 5.2, barDir: "col", barGrouping: "clustered", showLegend: true, legendPos: "b",
    valAxisMinVal: 10, valAxisMaxVal: 20, chartColors: [HEX.raw, HEX.clim, HEX.mbc, HEX.hybrid], showValue: false,
    objectName: "season chart",
  });
  await iconCard(s, 8.8, 1.5, 3.9, 2.45, fa.FaSun, "June-September", "Raw ECMWF is worse than climatology here. The hybrid has the lowest error: 12.53 against 13.09 for MBC.", "season jja", { dot: HEX.amber });
  await iconCard(s, 8.8, 4.15, 3.9, 2.45, fa.FaCloudShowersHeavy, "The rainy seasons", "MAM and SON carry the largest errors. The ML gain over MBC is smallest there (0.07-0.11 mm/week).", "season rains");
  s.addNotes("Source: SEASONAL_METRICS.csv of the refit retrospective, seasons by initialisation month.");

  // 12. Monthly skill
  s = content("The experiment");
  s.addText("Skill against climatology, month by month", { placeholder: "title" });
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  s.addChart(pres.charts.LINE, [
    { name: "Raw ECMWF", labels: months, values: [0.14, 0.11, 0.18, 0.01, 0.15, -0.29, -0.57, -0.59, -0.55, 0.16, 0.22, 0.28] },
    { name: "MBC", labels: months, values: [0.22, 0.24, 0.3, 0.19, 0.25, 0.13, 0.03, 0.0, 0.09, 0.35, 0.3, 0.28] },
    { name: "CatBoost hybrid", labels: months, values: [0.22, 0.26, 0.28, 0.21, 0.29, 0.15, 0.1, 0.13, 0.12, 0.35, 0.31, 0.32] },
  ], {
    ...chartBase("RMSE skill score against 2005-2021 climatology (above 0 = better than climatology)"),
    x: 0.6, y: 1.4, w: 8.3, h: 5.2, showLegend: true, legendPos: "b", lineSize: 2.5, lineDataSymbol: "circle", lineDataSymbolSize: 6,
    valAxisMinVal: -0.7, valAxisMaxVal: 0.4, valAxisLabelFormatCode: "0.0", chartColors: [HEX.raw, HEX.mbc, HEX.hybrid],
    objectName: "monthly skill chart",
  });
  s.addText(
    bullets([
      "Raw ECMWF is less accurate than climatology from June to September",
      "MBC lifts every month to at least climatology (August only just, 0.001)",
      "The CatBoost hybrid adds most where MBC is weakest: July to September (+0.03 to +0.13)",
      "Months are initialisation months, as in the training cases",
    ], 15),
    { x: 9.2, y: 1.6, w: 3.5, h: 4.9, color: C.text1, valign: "top", margin: 0, isTextBox: true, objectName: "monthly notes" },
  );
  s.addNotes("Source: DETERMINISTIC_SKILL_AGAINST_REFIT_CLIMATOLOGY.csv, column rmse_skill_against_2005_2021_climatology, month rows.");

  // 13. Countries
  s = content("The experiment");
  s.addText("Error by country", { placeholder: "title" });
  const ctry = [
    ["Tanzania", 23.75, 23.73, 25.2, 27.73], ["Kenya", 20.34, 20.44, 22.09, 23.82], ["Burundi", 20.12, 20.1, 23.31, 22.09],
    ["Rwanda", 19.23, 19.11, 24.97, 21.06], ["Uganda", 16.68, 16.87, 19.45, 18.95], ["Ethiopia", 16.35, 16.62, 19.09, 18.65],
    ["Somalia", 12.19, 12.23, 12.6, 14.85], ["South Sudan", 11.98, 12.47, 15.55, 13.22], ["Eritrea", 9.02, 9.63, 11.8, 10.27],
    ["Sudan", 6.16, 6.86, 9.43, 6.72], ["Djibouti", 4.69, 5.03, 11.23, 5.47],
  ];
  const head = ["Country", "Hybrid", "MBC", "Raw", "Clim."].map((t, j) => ({ text: t, options: { bold: true, color: HEX.white, fill: { color: HEX.forest }, align: j ? "right" : "left" } }));
  s.addTable(
    [head, ...ctry.map((r) => r.map((v, j) => {
      const best = j > 0 && v === Math.min(r[1], r[2], r[3], r[4]);
      return { text: j ? v.toFixed(2) : v, options: { bold: j === 0 || best, color: best ? HEX.forest : HEX.ink, align: j ? "right" : "left" } };
    }))],
    { x: 0.6, y: 1.4, w: 7.0, colW: [2.2, 1.2, 1.2, 1.2, 1.2], fontSize: 13, rowH: 0.42, border: { type: "solid", pt: 0.5, color: HEX.line }, valign: "middle", margin: 0.06, objectName: "country table" },
  );
  await iconCard(s, 8.0, 1.5, 4.7, 2.45, fa.FaMountain, "Wet south, hard to predict", "Tanzania, Kenya, Burundi and Rwanda have the largest errors. The hybrid and MBC are within 0.12 mm/week of each other.", "country south");
  await iconCard(s, 8.0, 4.15, 4.7, 2.45, fa.FaArrowTrendDown, "Dry north gains most", "Sudan, Djibouti, Eritrea and South Sudan: the hybrid cuts MBC's error by 0.3-0.7 mm/week and halves raw ECMWF's in Djibouti.", "country north", { dot: HEX.amber });
  s.addNotes("RMSE in mm/week, all months 2022-2024. Source: COUNTRY_METRICS_NAMED.csv. Lowest value per row in green bold. The same per-country RMSE now appears in the web app's country table.");

  // 14. Honest reading
  s = content("The experiment");
  s.addText("What the results do and do not say", { placeholder: "title" });
  card(s, 0.6, 1.45, 5.95, 5.15, "does say card");
  s.addText("They say", { x: 0.9, y: 1.6, w: 5.4, h: 0.55, fontSize: 20, bold: true, color: C.accent1, margin: 0, isTextBox: true, objectName: "does say heading" });
  s.addText(bullets([
    "Bias-corrected ECMWF is clearly better than raw ECMWF and than climatology in every season",
    "The ML residual is a consistent refinement: lowest error in every season and in 8 of 11 countries, within 0.12 mm/week of MBC in the other three",
    "Two separate checks (independent test, refit retrospective) agree",
  ], 15), { x: 0.9, y: 2.25, w: 5.4, h: 4.2, color: C.text1, valign: "top", margin: 0, isTextBox: true, objectName: "does say list" });
  card(s, 6.75, 1.45, 5.95, 5.15, "does not say card", "FDF6E3");
  s.addText("They do not say", { x: 7.05, y: 1.6, w: 5.4, h: 0.55, fontSize: 20, bold: true, color: C.accent2, margin: 0, isTextBox: true, objectName: "does not say heading" });
  s.addText(bullets([
    "How skilful live forecasts are: these are reforecasts; live weeks are verified one by one in the web app",
    "That the refit beats the pre-refit model: the difference is within its uncertainty",
    "Anything about probabilities: the hybrid gives one deterministic amount per cell",
  ], 15), { x: 7.05, y: 2.25, w: 5.4, h: 4.2, color: C.text1, valign: "top", margin: 0, isTextBox: true, objectName: "does not say list" });
  s.addNotes("8 of 11 countries: hybrid below MBC except Tanzania (23.75 vs 23.73), Rwanda (19.23 vs 19.11) and Burundi (20.12 vs 20.10). Seasons: hybrid lowest in all four.");

  // ---------------------------------------------------------------- web service
  pres.addSection({ title: "The web service" });
  s = pres.addSlide({ masterName: "SECTION", sectionTitle: "The web service" });
  s.addText("Part 2. The web service", { placeholder: "title" });
  s.addText("The ICPAC Week-2 Rainfall Outlook: the model above, issued and verified every week", { placeholder: "body" });

  // 16. Architecture
  s = content("The web service");
  s.addText("Architecture", { placeholder: "title" });
  const lanes = [
    ["Data in", ["ECMWF Open Data ensemble", "CHIRPS, TAMSAT", "ARC 2.0, RFE 2.0, GPM IMERG"], HEX.raw],
    ["Climate engine (Python)", ["Week-2 totals on 0.05° grid", "MBC + CatBoost hybrid", "Maps, NetCDF, country statistics", "Verification and provenance"], HEX.forest],
    ["Service (FastAPI)", ["Weekly cycle, one step at a time", "Bulletin drafts, review, publication", "Copilot with forecast tools", "Records in PostgreSQL, files in Blob"], HEX.deep],
    ["Website (Next.js)", ["Public forecast, maps, bulletin", "Staff tools behind a key", "6 site languages incl. Arabic RTL", "Dark mode, phone layout"], HEX.hybrid],
  ];
  for (let i = 0; i < lanes.length; i++) {
    const x = 0.6 + i * 3.08;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 1.45, w: 2.85, h: 0.7, rectRadius: 0.1, fill: { color: lanes[i][2] }, line: { color: lanes[i][2] }, objectName: "lane " + (i + 1) + " head" });
    s.addText(lanes[i][0], { x, y: 1.45, w: 2.85, h: 0.7, fontSize: 15, bold: true, color: C.background1, align: "center", valign: "middle", margin: 0, isTextBox: true, objectName: "lane " + (i + 1) + " title" });
    card(s, x, 2.3, 2.85, 2.9, "lane " + (i + 1));
    s.addText(bullets(lanes[i][1], 14), { x: x + 0.15, y: 2.45, w: 2.6, h: 2.65, color: C.text1, valign: "top", margin: 0, isTextBox: true, objectName: "lane " + (i + 1) + " list" });
    if (i < lanes.length - 1) s.addText("›", { x: x + 2.83, y: 3.4, w: 0.27, h: 0.6, fontSize: 24, color: C.accent6, align: "center", margin: 0, isTextBox: true, objectName: "lane arrow " + (i + 1) });
  }
  s.addText(
    [
      { text: "Runs on: ", options: { bold: true, color: C.text2 } },
      { text: "Azure Container Apps (API) and Vercel (website) today, with n8n for signed weekly automation and OpenRouter for open-weight language models. Containerised, so it can move to ICPAC's own servers.", options: {} },
    ],
    { x: 0.6, y: 5.45, w: 12.1, h: 1.2, fontSize: 15, color: C.text1, valign: "middle", margin: 0, isTextBox: true, objectName: "hosting note" },
  );
  s.addNotes("docs/architecture.md. The frontend computes nothing scientific: every number, map and label comes from the API.");

  // 17. Weekly cycle
  s = content("The web service");
  s.addText("The weekly cycle", { placeholder: "title" });
  const cycle = [
    ["1", "Sunday 00 UTC ECMWF run", "Downloaded and checked: members, steps, grid"],
    ["2", "Forecast package", "Raw, MBC and hybrid layers; checksums for every file"],
    ["3", "Maps and statistics", "ICPAC colour scale, 11 countries, regional mean and RMSE"],
    ["4", "Bulletin draft", "Word template, AI-written wording with every figure checked"],
    ["5", "Review and publish", "Forecaster edits, reviewer approves, publisher releases"],
    ["6", "Verification", "About two days after the week: CHIRPS, ARC 2.0, RFE 2.0, IMERG"],
  ];
  for (let i = 0; i < cycle.length; i++) {
    const x = 0.6 + (i % 3) * 4.1, y = 1.5 + Math.floor(i / 3) * 2.6;
    card(s, x, y, 3.9, 2.35, "cycle step " + cycle[i][0]);
    s.addShape(pres.shapes.OVAL, { x: x + 0.25, y: y + 0.25, w: 0.6, h: 0.6, fill: { color: i === 5 ? HEX.amber : HEX.forest }, line: { color: i === 5 ? HEX.amber : HEX.forest }, objectName: "cycle number circle " + cycle[i][0] });
    s.addText(cycle[i][0], { x: x + 0.25, y: y + 0.25, w: 0.6, h: 0.6, fontSize: 18, bold: true, color: C.background1, align: "center", valign: "middle", margin: 0, isTextBox: true, objectName: "cycle number " + cycle[i][0] });
    s.addText(cycle[i][1], { x: x + 1.0, y: y + 0.22, w: 2.75, h: 0.66, fontSize: 16, bold: true, color: C.text2, valign: "middle", margin: 0, isTextBox: true, objectName: "cycle title " + cycle[i][0] });
    s.addText(cycle[i][2], { x: x + 0.25, y: y + 1.05, w: 3.4, h: 1.15, fontSize: 14, color: C.text1, valign: "top", margin: 0, isTextBox: true, objectName: "cycle text " + cycle[i][0] });
  }
  s.addNotes("Every step is a background task recorded with who started it (backend/app/services/operations.py). When the upper-air fields are late, the forecast is issued from MBC and says so; nothing is filled in.");

  // 18. Forecast page
  s = content("The web service");
  s.addText("The forecast page: mean and typical error", { placeholder: "title" });
  screen(s, "forecast.png", 0.6, 1.45, 7.6, "Forecast page with stat tiles and the rainfall map", "forecast screenshot");
  s.addText(bullets([
    "Regional mean of the issued layer beside the raw ECMWF mean",
    "Typical error (RMSE) for the issue month and over all months, from the 2022-2024 scores of the model in use",
    "Per-country mean, median, range and RMSE",
    "Raw, MBC and hybrid layers on one map; downloads in NetCDF, CSV and PNG",
  ], 15), { x: 8.6, y: 1.5, w: 4.1, h: 4.9, color: C.text1, valign: "top", margin: 0, isTextBox: true, objectName: "forecast bullets" });
  s.addText("Screens from a local test run of the service (test input data).", { x: 0.6, y: 6.4, w: 7.6, h: 0.35, fontSize: 11, italic: true, color: C.accent6, margin: 0, isTextBox: true, objectName: "forecast caption" });
  s.addNotes("The RMSE is labelled as the typical grid-cell error in the 2022-2024 reforecasts, never as the error of this week; the week's own error appears once it is verified.");

  // 19. Bulletin
  s = content("The web service");
  s.addText("The weekly bulletin, written for people", { placeholder: "title" });
  screen(s, "bulletin.png", 5.1, 1.45, 7.6, "Bulletin page with headline, decision-support note and map", "bulletin screenshot");
  s.addText(bullets([
    "Drafted from the forecast in ICPAC's Word template, maps placed automatically",
    "An open-weight language model rewrites the wording as a forecaster would; every number is checked against the forecast and the length is capped",
    "A humanizer rule set and skill remove AI-sounding phrasing",
    "Translated into Kiswahili, French, Arabic, Amharic and Somali",
    "Forecaster, reviewer and publisher sign off before release",
  ], 15), { x: 0.6, y: 1.5, w: 4.2, h: 5.1, color: C.text1, valign: "top", margin: 0, isTextBox: true, objectName: "bulletin bullets" });
  s.addText("Screens from a local test run of the service (test input data).", { x: 5.1, y: 6.3, w: 7.6, h: 0.35, fontSize: 11, italic: true, color: C.accent6, margin: 0, isTextBox: true, objectName: "bulletin caption" });
  s.addNotes("chatbot/bulletin_writer.py and chatbot/tone.py; .claude/skills/bulletin-humanizer. A rewrite that adds or drops a figure, runs more than about a third longer, or reads as machine-written is refused and the computed draft stands.");

  // 20. Copilot
  s = content("The web service");
  s.addText("The Forecaster Copilot", { placeholder: "title" });
  const cp = [
    [fa.FaComments, "Ask in plain words", "Staff ask about this week's forecast, a country or a past week, in English or a member-state language"],
    [fa.FaToolbox, "Answers from tools", "The model calls the service for forecast values, country statistics and verification, then writes in climate language"],
    [fa.FaShieldHalved, "Figures checked", "An answer whose numbers are not in the tool results is rejected; no invented climatology or certainty"],
    [fa.FaServer, "Open-weight models", "gpt-oss-120b through OpenRouter, with Qwen3 and Kimi K2 as fallbacks; a self-hosted model can replace them"],
  ];
  for (let i = 0; i < cp.length; i++) {
    await iconCard(s, 0.6 + (i % 2) * 6.15, 1.5 + Math.floor(i / 2) * 2.6, 5.95, 2.35, cp[i][0], cp[i][1], cp[i][2], "copilot " + (i + 1));
  }
  s.addNotes("chatbot/agent.py (tools and system prompt), chatbot/conversation.py. Past weeks are judged against CHIRPS and the other rainfall datasets, with each one's difference shown.");

  // 21. Verification
  s = content("The web service");
  s.addText("Verification and model evidence", { placeholder: "title" });
  screen(s, "evidence.png", 0.6, 1.45, 7.6, "Model evidence page with regional RMSE bars", "evidence screenshot");
  s.addText(bullets([
    "Each live week is scored automatically against CHIRPS, with ARC 2.0, RFE 2.0 and GPM IMERG as further references",
    "Seasonal scores accumulate as weeks are verified",
    "The frozen 2022-2024 evidence (tables, maps, figures) is served only after its checksum matches",
    "Every score page says whether it is independent or retrospective",
  ], 15), { x: 8.6, y: 1.5, w: 4.1, h: 5.0, color: C.text1, valign: "top", margin: 0, isTextBox: true, objectName: "verification bullets" });
  s.addText("Screens from a local test run of the service; the evidence figures are the real frozen scores.", { x: 0.6, y: 6.4, w: 7.6, h: 0.35, fontSize: 11, italic: true, color: C.accent6, margin: 0, isTextBox: true, objectName: "evidence caption" });
  s.addNotes("backend/app/services/evidence.py checks SHA256SUMS.txt before reading any table.");

  // 22. Engineering
  s = content("The web service");
  s.addText("Built to be trusted and maintained", { placeholder: "title" });
  stat(s, 0.6, 1.4, 2.9, "450+", "backend tests, run on every change in CI", "stat tests");
  stat(s, 3.7, 1.4, 2.9, "100%", "of package files checksummed and re-checked when served", "stat checksums");
  stat(s, 6.8, 1.4, 2.9, "6", "site languages, with right-to-left Arabic", "stat languages");
  stat(s, 9.9, 1.4, 2.8, "0", "values filled in when an input is missing", "stat honesty", C.accent2);
  card(s, 0.6, 4.0, 12.1, 2.6, "engineering card");
  s.addText(bullets([
    "Provenance in every forecast: model, inputs, code version, configuration checksum",
    "Public visitors read; staff actions need a key; administrators confirm real-time inputs",
    "Docker images for the API, website and a self-hosted language model",
  ], 15), { x: 0.95, y: 4.2, w: 11.4, h: 2.25, color: C.text1, valign: "middle", margin: 0, isTextBox: true, objectName: "engineering list" });
  s.addNotes("450+ = 447 passed and 5 skipped in the full backend run of 22 Nov 2026; the frontend has its own unit and browser tests.");

  // ---------------------------------------------------------------- next
  pres.addSection({ title: "What comes next" });
  s = pres.addSlide({ masterName: "SECTION", sectionTitle: "What comes next" });
  s.addText("Part 3. What comes next", { placeholder: "title" });
  s.addText("The most promising advances, and how I can help ICPAC", { placeholder: "body" });

  // 24. Advancements
  s = content("What comes next");
  s.addText("The best advances to make", { placeholder: "title" });
  const adv = [
    [fa.FaLayerGroup, "Run the predictor kit", "124 candidate drivers (SST indices, MJO, IOD, soil moisture, pressure) reduced by PCA/EOF in 19 groups, tested for skill beyond the 17 PCs"],
    [fa.FaChartArea, "Probabilistic ML", "Quantile or distributional models (CRPS-trained) to give tercile and threshold probabilities, verified with reliability and Brier scores"],
    [fa.FaMap, "Generative downscaling", "A conditional GAN or diffusion model on the ECMWF ensemble, in the spirit of ICPAC's cGAN work, for realistic local extremes"],
    [fa.FaBrain, "AI weather models", "Test ECMWF's AIFS and similar data-driven ensembles as Week-2 inputs alongside IFS"],
    [fa.FaRotate, "Learning from live weeks", "Use verified operational weeks to monitor drift and plan refits"],
    [fa.FaBuilding, "ICPAC hosting", "Move the service to ICPAC infrastructure for long-term operation"],
  ];
  for (let i = 0; i < adv.length; i++) {
    await iconCard(s, 0.6 + (i % 3) * 4.1, 1.45 + Math.floor(i / 3) * 2.65, 3.9, 2.45, adv[i][0], adv[i][1], adv[i][2], "advance " + (i + 1), { dot: i < 3 ? HEX.forest : HEX.amber });
  }
  s.addNotes("Ordered by expected value for Week-2 skill. The predictor kit is built (training/predictors) but has not been run; the others are proposals.");

  // 25. How I can help
  s = content("What comes next");
  s.addText("How I can help ICPAC as a data scientist", { placeholder: "title" });
  const help = [
    [fa.FaDatabase, "Data pipelines", "Reliable, checked downloads and archives of ECMWF, CHIRPS and satellite rainfall for every product team"],
    [fa.FaGears, "Operational ML", "Take research models into weekly operations with tests, provenance and monitoring, as done here"],
    [fa.FaChartLine, "Verification at scale", "One verification service for ICPAC's weekly, monthly and seasonal products, open to member states"],
    [fa.FaLanguage, "Language tools", "Bulletins and answers in member-state languages, with figures checked and forecaster review"],
    [fa.FaChalkboardUser, "Capacity building", "Training NMHS staff in Python, ML post-processing and verification, with the code as teaching material"],
    [fa.FaHandshake, "Partnerships", "Shared, documented code for ECMWF, WMO and university collaborations"],
  ];
  for (let i = 0; i < help.length; i++) {
    await iconCard(s, 0.6 + (i % 3) * 4.1, 1.45 + Math.floor(i / 3) * 2.65, 3.9, 2.45, help[i][0], help[i][1], help[i][2], "help " + (i + 1));
  }
  s.addNotes("Tie each card to something already built in this project: the input readers, the weekly cycle, the verification pages, the bulletin writer and translations, the HPC kit and documentation.");

  // 26. Roadmap
  s = content("What comes next");
  s.addText("A practical roadmap", { placeholder: "title" });
  const road = [
    ["Next 3 months", ["Run the predictor kit on the HPC and report its skill", "Move the service to ICPAC hosting", "Native-speaker review of the translations"]],
    ["3-6 months", ["Probabilistic Week-2 product with reliability checks", "Live-week verification summary for each season", "Training session for member-state forecasters"]],
    ["6-12 months", ["Generative downscaling and AI-model inputs, tested against the current hybrid", "Refit with the best new predictors", "Extend to Week-3/4 if skill allows"]],
  ];
  for (let i = 0; i < road.length; i++) {
    const x = 0.6 + i * 4.1;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 1.5, w: 3.9, h: 0.75, rectRadius: 0.1, fill: { color: [HEX.forest, HEX.hybrid, HEX.amber][i] }, line: { color: [HEX.forest, HEX.hybrid, HEX.amber][i] }, objectName: "road head " + (i + 1) });
    s.addText(road[i][0], { x, y: 1.5, w: 3.9, h: 0.75, fontSize: 18, bold: true, color: C.background1, align: "center", valign: "middle", margin: 0, isTextBox: true, objectName: "road title " + (i + 1) });
    card(s, x, 2.4, 3.9, 3.3, "road " + (i + 1));
    s.addText(bullets(road[i][1], 17), { x: x + 0.2, y: 2.6, w: 3.5, h: 2.95, color: C.text1, valign: "top", margin: 0, isTextBox: true, objectName: "road list " + (i + 1) });
  }

  // 27. Close
  pres.addSection({ title: "Close" });
  s = pres.addSlide({ masterName: "TITLE_DARK", sectionTitle: "Close" });
  s.addText("Thank you", { placeholder: "title" });
  s.addText(
    [
      { text: "Questions and discussion", options: { breakLine: true } },
      { text: "Live service: icpac-ml-ai-product-three.vercel.app", options: { fontSize: 16, color: C.accent2 } },
    ],
    { placeholder: "body" },
  );

  await pres.writeFile({ fileName: OUT });
  if (process.env.APPLY_THEME) {
    const { applyTheme } = require(process.env.APPLY_THEME);
    await applyTheme(OUT, THEME);
  }
  console.log("Wrote " + OUT);
}

build().catch((err) => {
  console.error(err);
  process.exit(1);
});
