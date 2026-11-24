/*
 * Internship presentation (20 minutes): from the literature and the first statistical
 * experiments to the MBC + AI/ML model, the drivers in progress and the web service.
 * Light backgrounds, the ICPAC logo on every slide, Beamer-style titled blocks.
 *
 *   NODE_PATH=<folder with pptxgenjs> node docs/presentation/build_deck_v2.js out.pptx
 *   node <pptx skill>/scripts/apply_theme.js out.pptx   (done here when APPLY_THEME is set)
 *
 * Every score comes from artifacts/verification (see each slide's notes for the file).
 */
const path = require("path");
const pptxgen = require("pptxgenjs");

const OUT = process.argv[2] || path.join(__dirname, "ICPAC_Week2_AI_ML_Internship.pptx");
const A = (f) => path.join(__dirname, "assets_v2", f);

const THEME = {
  name: "ICPAC Light",
  headFontFace: "Calibri",
  bodyFontFace: "Calibri",
  colors: {
    dk1: "1B2A22", lt1: "FFFFFF", dk2: "0B5D33", lt2: "EEF6F1",
    accent1: "0F8A43", accent2: "E9A818", accent3: "2A78D6",
    accent4: "E0802F", accent5: "1BAF7A", accent6: "66706A",
    hlink: "1F62A8", folHlink: "6D2E46",
  },
};
const H = {
  ink: "1B2A22", deep: "0B5D33", green: "0F8A43", pale: "EEF6F1", amber: "E9A818",
  amberPale: "FDF4DF", blue: "2A78D6", bluePale: "EAF2FC", raw: "2A78D6", mbc: "E0802F",
  hyb: "1BAF7A", clim: "9AA19B", muted: "66706A", line: "D7DFDA", white: "FFFFFF",
  red: "C0392B", redPale: "FBEBE9", purple: "6B4FA0", purplePale: "F1EDF8",
};

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.33 x 7.5 in
pres.title = "AI and machine learning for Week-2 rainfall prediction in Eastern Africa";
pres.author = "Sangura J. Nyongesa";
pres.company = "IGAD Climate Prediction and Applications Centre (ICPAC)";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
const C = pres.SchemeColor;

const FOOT = "S. J. Nyongesa · ICPAC internship 2026 · AI/ML for Week-2 rainfall in Eastern Africa";
const LOGO = { path: A("logo_icpac.png"), x: 12.42, y: 0.16, w: 0.62, h: 0.82 };

pres.defineSlideMaster({
  title: "TITLE",
  background: { color: H.white },
  objects: [{ image: { path: A("logo_icpac.png"), x: 0.6, y: 0.45, w: 1.06, h: 1.4 } }],
});
pres.defineSlideMaster({
  title: "CONTENT",
  background: { color: H.white },
  margin: [0.4, 0.6, 0.6, 0.6],
  objects: [
    { image: LOGO },
    {
      placeholder: {
        options: { name: "title", type: "title", x: 0.6, y: 0.44, w: 11.6, h: 0.72, fontSize: 28, bold: true, color: C.text2, valign: "middle", align: "left", margin: 0 },
        text: "Slide title",
      },
    },
    { text: { text: FOOT, options: { x: 0.6, y: 7.08, w: 10, h: 0.28, fontSize: 10, color: C.accent6, margin: 0 } } },
  ],
  slideNumber: { x: 12.2, y: 7.08, w: 0.55, h: 0.28, fontSize: 10, color: C.accent6, align: "right" },
});

// ------------------------------------------------------------------ helpers
let n = 0;
function content(tag, title, section) {
  const s = pres.addSlide({ masterName: "CONTENT", sectionTitle: section });
  s.addText(title, { placeholder: "title" });
  if (tag) s.addText(tag, { x: 0.6, y: 0.18, w: 8, h: 0.3, fontSize: 12, bold: true, color: C.accent2, margin: 0, isTextBox: true, charSpacing: 1 });
  n += 1;
  return s;
}
function txt(s, text, o) {
  s.addText(text, Object.assign({ fontSize: 14, color: C.text1, margin: 0, valign: "top", isTextBox: true, paraSpaceAfter: 4 }, o));
}
/** A titled block: coloured header band and a tinted body, as in a Beamer deck. */
function block(s, { x, y, w, h, title, color = H.green, tint = H.pale, body, size = 14, name }) {
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, fill: { color: tint }, line: { color: tint }, rectRadius: 0.08, objectName: (name || title) + " block" });
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h: 0.44, fill: { color }, line: { color }, rectRadius: 0.08 });
  s.addShape(pres.shapes.RECTANGLE, { x, y: y + 0.24, w, h: 0.2, fill: { color }, line: { color } });
  s.addText(title, { x: x + 0.16, y, w: w - 0.32, h: 0.44, fontSize: 15, bold: true, color: H.white, margin: 0, valign: "middle", isTextBox: true });
  if (body) txt(s, body, { x: x + 0.16, y: y + 0.56, w: w - 0.32, h: h - 0.66, fontSize: size });
}
function bullets(items, o = {}) {
  return items.map((t, i) => {
    const runs = typeof t === "string" ? [{ text: t }] : t;
    return runs.map((r, j) => ({
      text: r.text,
      options: Object.assign({}, j === 0 ? { bullet: { indent: 14 } } : {}, r.options || {}, j === runs.length - 1 && i < items.length - 1 ? { breakLine: true } : {}, o),
    }));
  }).flat();
}
const B = (text, extra = {}) => ({ text, options: Object.assign({ bold: true }, extra) });
function chip(s, x, y, w, h, label, fill, color = H.white, size = 13) {
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, fill: { color: fill }, line: { color: fill }, rectRadius: 0.1 });
  s.addText(label, { x, y, w, h, fontSize: size, bold: true, color, align: "center", valign: "middle", margin: 2, isTextBox: true });
}
function arrow(s, x, y, w = 0.32) {
  s.addShape(pres.shapes.RIGHT_ARROW, { x, y, w, h: 0.26, fill: { color: H.clim }, line: { color: H.clim } });
}
function stat(s, x, y, w, big, label, color = H.green) {
  s.addText(big, { x, y, w, h: 0.8, fontSize: 40, bold: true, color, margin: 0, isTextBox: true, valign: "bottom" });
  s.addText(label, { x, y: y + 0.84, w, h: 0.62, fontSize: 13, color: H.muted, margin: 0, isTextBox: true, valign: "top" });
}
function image(s, file, x, y, w, h, caption, alt) {
  s.addImage({ path: A(file), x, y, w, h, altText: alt || caption || file });
  if (caption) s.addText(caption, { x, y: y + h + 0.04, w, h: 0.3, fontSize: 12, color: H.muted, align: "center", margin: 0, isTextBox: true });
}
const chartText = {
  catAxisLabelColor: H.muted, valAxisLabelColor: H.muted, catAxisLabelFontSize: 12, valAxisLabelFontSize: 12,
  catAxisLabelFontFace: "+mn-lt", valAxisLabelFontFace: "+mn-lt", dataLabelFontFace: "+mn-lt", legendFontFace: "+mn-lt",
  titleFontFace: "+mn-lt", titleColor: H.ink, titleFontSize: 14, dataLabelFontSize: 12, dataLabelColor: H.ink, legendFontSize: 12,
};

// ================================================================= 1. title
pres.addSection({ title: "Introduction" });
{
  const s = pres.addSlide({ masterName: "TITLE", sectionTitle: "Introduction" });
  n += 1;
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 8.15, y: 0.45, w: 4.6, h: 6.6, fill: { color: H.pale }, line: { color: H.pale }, rectRadius: 0.12, objectName: "map panel" });
  s.addImage({ path: A("mean_cat.png"), x: 8.35, y: 0.75, w: 4.2, h: 4.17, altText: "Mean Week-2 rainfall, MBC + AI/ML, 2022 to 2024" });
  s.addText("Mean Week-2 rainfall from the MBC + AI/ML model, 2022–2024 (551 forecasts)", { x: 8.4, y: 5.05, w: 4.1, h: 0.6, fontSize: 12, color: H.muted, margin: 0, isTextBox: true });
  s.addText("ICPAC INTERNSHIP · NOVEMBER 2026", { x: 0.6, y: 2.15, w: 7.2, h: 0.35, fontSize: 13, bold: true, color: H.amber, charSpacing: 2, margin: 0, isTextBox: true });
  s.addText("AI and machine learning for Week-2 rainfall prediction in Eastern Africa", { x: 0.6, y: 2.55, w: 7.3, h: 1.9, fontSize: 38, bold: true, color: H.deep, margin: 0, valign: "top", isTextBox: true });
  s.addText("From the first bias-correction experiments to an operational MBC + AI/ML forecast, bulletin and Copilot", { x: 0.6, y: 4.5, w: 7.2, h: 0.8, fontSize: 17, color: H.ink, margin: 0, isTextBox: true });
  s.addText([
    { text: "Sangura J. Nyongesa", options: { bold: true, fontSize: 18, color: H.ink, breakLine: true } },
    { text: "Supervisor: Dr. Masilin Gudoshava · Climate Prediction and Climate Services, ICPAC", options: { fontSize: 14, color: H.muted } },
  ], { x: 0.6, y: 5.55, w: 7.3, h: 0.9, margin: 0, isTextBox: true });
  s.addNotes("[0:30] Introduce yourself and the internship topic: Application of AI and ML for medium-range (7-14 day) prediction in Eastern Africa. The talk follows the work in order: literature, statistical calibration, ML models, the final refit, results, drivers, the web service, and what comes next.");
}

// ================================================================= 2. objective and answer
{
  const s = content("00 · OVERVIEW", "The internship objective, and what the work delivered", "Introduction");
  block(s, {
    x: 0.6, y: 1.4, w: 5.6, h: 2.75, title: "Objective set by ICPAC",
    body: "Explore AI and ML to improve 7–14-day (Week-2) forecasts over Eastern Africa: preprocess historical and operational data, develop and evaluate AI models, identify the important climate drivers and assess forecast skill, for early warning in agriculture, water, disaster risk and food security.",
  });
  stat(s, 6.6, 1.35, 2.0, "12.2%", "lower RMSE than raw ECMWF (2022–2024, 551 forecasts)");
  stat(s, 8.75, 1.35, 2.0, "245", "candidate climate drivers; 175 ready on the HPC", H.amber);
  stat(s, 10.9, 1.35, 2.0, "Weekly", "forecast, bulletin, Copilot and verification online", H.blue);
  s.addText("The path, in order", { x: 0.6, y: 4.5, w: 6, h: 0.35, fontSize: 15, bold: true, color: H.deep, margin: 0, isTextBox: true });
  const steps = ["Literature review", "Statistical calibration", "Four ML models", "LOYO and final refit", "Live web service", "Drivers and next models"];
  const fills = [H.blue, H.green, H.green, H.amber, H.blue, H.purple];
  steps.forEach((t, i) => {
    const x = 0.6 + i * 2.06;
    chip(s, x, 5.0, 1.72, 0.85, t, fills[i]);
    if (i < steps.length - 1) arrow(s, x + 1.74, 5.3);
  });
  txt(s, "Most of the gain over raw ECMWF comes from multiplicative bias correction (MBC); the AI/ML layer adds a smaller, consistent improvement on top, largest from June to September and in the drier north.", { x: 0.6, y: 6.1, w: 12.1, h: 0.8, fontSize: 14, color: H.muted });
  s.addNotes("[0:45] 12.2% = 1 - 15.156/17.269 (FINAL_REFIT_RETROSPECTIVE_2022_2024_20261027/tables/GLOBAL_METRICS.csv). 245 drivers / 175 ready: HPC readiness check of 23 Nov 2026 (feature_dependencies_245.csv). Walk the path left to right: it is also the order of the talk.");
}

// ================================================================= 3. literature
pres.addSection({ title: "Literature and data" });
{
  const s = content("01 · LITERATURE REVIEW", "What the literature says about Week-2 post-processing", "Literature and data");
  const hdr = (t) => ({ text: t, options: { bold: true, color: H.white, fill: { color: H.deep } } });
  const rows = [
    [hdr("Approach"), hdr("Key references"), hdr("In this work")],
    ["Bias correction (scaling)", "Standard S2S post-processing practice", "Used: MBC"],
    ["Calibrated distributions (EMOS, CSGD)", "Gneiting et al. 2005; Scheuerer & Hamill 2015", "Next step"],
    ["Gradient-boosted trees", "Chen & Guestrin 2016; Ke et al. 2017; Prokhorenkova et al. 2018", "Used: AI/ML residual"],
    ["Neural post-processing", "Rasp & Lerch 2018", "Next step"],
    ["Generative ML (cGAN) over East Africa", "Antonio et al. 2025 (ICPAC, SEWAA)", "Builds on it"],
    ["AI weather models", "AIFS (Lang et al. 2024); GenCast (Price et al. 2025); Aurora (Bodnar et al. 2025)", "Future inputs"],
    ["Predictability and truth data", "Vitart et al. 2017 (S2S); Funk et al. 2015 (CHIRPS)", "Used"],
  ];
  s.addTable(rows, { x: 0.6, y: 1.4, w: 7.7, colW: [2.45, 3.75, 1.5], fontSize: 13, color: H.ink, border: { type: "solid", color: H.line, pt: 0.75 }, fill: { color: H.white }, rowH: 0.56, valign: "middle", margin: [2, 6, 2, 6] });
  block(s, {
    x: 8.6, y: 1.4, w: 4.15, h: 5.45, title: "What I found", color: H.amber, tint: H.amberPale,
    body: bullets([
      [B("Correct, don't replace. "), { text: "Calibrated ECMWF beats raw ECMWF; post-processing is the standard route." }],
      [B("Trees for tables, networks for maps. "), { text: "Boosted trees are strong on per-cell predictors; U-Nets and GANs need whole maps and GPUs." }],
      [B("Week 2 needs slow drivers. "), { text: "Past day 10, skill comes from the MJO, ENSO, the IOD and soil moisture, not the weather itself." }],
      [B("Probabilities matter. "), { text: "Users need chances of heavy rain, not one number." }],
    ], { paraSpaceAfter: 8 }),
  });
  s.addNotes("[1:15] Read the table by the right-hand column: what was used, what is next. The four findings shaped the design: start from bias correction, add a tree model on top, then drivers and probabilities. References are listed in docs/model_roadmap.md.");
}

// ================================================================= 4. data and HPC
{
  const s = content("02 · DATA", "Data: 20 years of ECMWF reforecasts on ICPAC's 0.05° grid", "Literature and data");
  block(s, { x: 0.6, y: 1.4, w: 3.9, h: 1.55, title: "Forecasts", body: "ECMWF S2S reforecasts 2005–2024, 10 members, an initialisation every two days. Live: ECMWF Open Data ensemble." });
  block(s, { x: 0.6, y: 3.1, w: 3.9, h: 1.55, title: "Truth", body: "CHIRPS v2.0 Week-2 totals at 0.05°. Live checks also use ARC 2.0, RFE 2.0 and GPM IMERG." });
  block(s, { x: 0.6, y: 4.8, w: 3.9, h: 2.05, title: "Upper air", body: "15 fields (humidity, winds, moisture flux, temperature, height, shear) at 850–200 hPa, days 8–14, as ensemble mean and spread." });
  // timeline
  const x0 = 5.0, yr = (y) => x0 + ((y - 2005) / 20) * 7.5;
  s.addText("How the years were used", { x: x0, y: 1.4, w: 7.7, h: 0.35, fontSize: 15, bold: true, color: H.deep, margin: 0, isTextBox: true });
  const bar = (label, a, b, y, fill) => chip(s, yr(a), y, yr(b + 1) - yr(a) - 0.04, 0.5, label, fill, H.white, 12);
  s.addText("Pre-refit", { x: x0, y: 1.95, w: 2, h: 0.3, fontSize: 13, color: H.muted, margin: 0, isTextBox: true });
  bar("Train 2005–2019", 2005, 2019, 2.25, H.green); bar("Valid.", 2020, 2021, 2.25, H.amber); bar("Test 22–24", 2022, 2024, 2.25, H.blue);
  s.addText("Final refit", { x: x0, y: 2.95, w: 2, h: 0.3, fontSize: 13, color: H.muted, margin: 0, isTextBox: true });
  bar("Train 2005–2021 (operational model)", 2005, 2021, 3.25, H.deep); bar("Retro.", 2022, 2024, 3.25, H.clim);
  [2005, 2010, 2015, 2020, 2024].forEach((y) => s.addText(String(y), { x: yr(y) - 0.3, y: 3.8, w: 0.6, h: 0.25, fontSize: 11, color: H.muted, align: "center", margin: 0, isTextBox: true }));
  stat(s, 5.0, 4.3, 2.4, "205,999", "land cells on the 0.05° ICPAC grid (11 states)");
  stat(s, 7.6, 4.3, 2.4, "647 M", "training rows, 3,148 forecasts (2005–2021)", H.amber);
  stat(s, 10.2, 4.3, 2.5, "113 M", "test rows, 551 forecasts (2022–2024)", H.blue);
  txt(s, "Every row was used, with no subsampling, on the ICPAC HPC.", { x: 5.0, y: 6.3, w: 7.7, h: 0.4, fontSize: 14, bold: true, color: H.deep });
  s.addNotes("[1:00] Counts: provenance/README_FIRST.txt and FINAL_REFIT_MODEL_MANIFEST.json (rows 647,228,800; cases 3,148). Test rows 113,285,600 (foundational_validation_independent_comparison.csv). The 2022-2024 years were held out for the pre-refit test; the refit then used 2005-2021.");
}


// ================================================================= 4b. preprocessing
{
  const s = content("02 · DATA PREPROCESSING", "Data preprocessing: from raw files to training rows", "Literature and data");
  const steps = [
    ["Download and check", "ECMWF GRIB, CHIRPS NetCDF on the HPC; members, steps and grid checked", H.blue],
    ["Week-2 totals", "ECMWF days 8–14 (lead 192–336 h); CHIRPS daily summed over the same 7 days", H.blue],
    ["Ensemble statistics", "Mean and spread of the 10 members for rainfall and 15 upper-air fields", H.green],
    ["Regrid and mask", "1.5° fields to the 0.05° ICPAC grid; 11-country mask, 205,999 cells", H.green],
    ["Clean", "Cells without CHIRPS are dropped, never filled; area weights cos(latitude)", H.amber],
    ["Reduce", "Standardise the 30 upper-air predictors; PCA to 17 components, fitted on training years only", H.amber],
    ["Seal", "Fixed feature schema and checksums for every file; the model refuses mismatched inputs", H.deep],
  ];
  steps.forEach(([t, d, c], i) => {
    const col = i < 4 ? 0 : 1, row = i < 4 ? i : i - 4;
    const x = 0.6 + col * 6.2, y = 1.45 + row * 1.33;
    chip(s, x, y, 0.62, 0.62, String(i + 1), c, H.white, 16);
    s.addText([{ text: t, options: { bold: true, breakLine: true } }, { text: d, options: { color: H.muted } }], { x: x + 0.8, y: y - 0.08, w: 5.1, h: 1.05, fontSize: 14, margin: 0, isTextBox: true, valign: "top" });
  });
  block(s, { x: 6.8, y: 5.45, w: 5.95, h: 1.42, title: "Rule throughout", color: H.red, tint: H.redPale, body: "Anything fitted (MBC, PCA, models) sees training years only: no information from the test years." });
  s.addNotes("[0:50] Leads 192-336 h and 15 fields x mean/spread = 30 predictors: hybrid model provenance. Mask 205,999 cells, cos(latitude) weights and missing CHIRPS rows omitted: FULLGRID_EXPERIMENT_MANIFEST (canonical_fullgrid_stats_mbc.py). PCA fitted on 2005-2019 (pre-refit) and 2005-2021 (refit).");
}

// ================================================================= 5. statistical calibration
pres.addSection({ title: "Methods" });
{
  const s = content("03 · STATISTICAL CALIBRATION", "Statistical calibration: what I compared, and why MBC was kept", "Methods");
  block(s, {
    x: 0.6, y: 1.4, w: 6.0, h: 5.45, title: "Candidates, all scored on 2020–2021",
    body: bullets([
      [B("Linear regression (OLS): "), { text: "Ŷ = β₀ + βᵀx, x = 6 core inputs (ensemble mean and spread, place, season)" }],
      [B("Principal-component regression: "), { text: "Ŷ = β₀ + βᵀx + γᵀ[PC₁ … PCₖ], k = 5, 10, 13, 17" }],
      [B("Ridge: "), { text: "minimise Σ(O − Ŷ)² + λ‖β‖²" }],
      [B("Elastic net: "), { text: "minimise Σ(O − Ŷ)² + λ[α‖β‖₁ + (1 − α)‖β‖²]" }],
      [B("Additive spline: "), { text: "hinge terms max(0, X̄ − kⱼ) on the ensemble mean and spread" }],
      [B("First MBC (E1): "), { text: "R = clip(Ō / max(F̄, 0.1), 0.05, 20), per month and cell" }],
      [B("MBC, 19 variants: "), { text: "monthly, seasonal or annual factors × prior λ = 50, 500, 2000 mm × cap 3 or 5, plus one regional factor" }],
    ], { paraSpaceAfter: 7 }),
  });
  block(s, {
    x: 6.9, y: 1.4, w: 5.85, h: 3.55, title: "Kept: multiplicative bias correction (MBC)", color: H.deep,
    body: [
      { text: "R(m, c) = clip[ (ΣO + λg) / (ΣF + λ), 0.2, 3 ]", options: { bold: true, fontSize: 16, color: H.deep, breakLine: true } },
      { text: "MBC = max( X̄ · R(m, c), 0 )", options: { bold: true, fontSize: 16, color: H.deep, breakLine: true } },
      { text: " ", options: { fontSize: 6, breakLine: true } },
      { text: "O, F: observed and forecast Week-2 totals of the training cases for month m and cell c; X̄: this week's ensemble mean; g: the area-weighted domain ratio; λ = 500 mm steadies dry or sparse cells.", options: { fontSize: 14 } },
    ],
  });
  block(s, {
    x: 6.9, y: 5.1, w: 5.85, h: 1.75, title: "Why", color: H.amber, tint: H.amberPale,
    body: "Like recalibrating a rain gauge that reads 30% high, month by month and place by place. A ratio cannot make negative rain and keeps dry cells dry. Best variant on 2020–2021: monthly, λ = 500, cap 3 (RMSE 14.37 mm/week).",
  });
  s.addNotes("[1:30] Candidates: artifacts/bundles/.../provenance/canonical_fullgrid_stats_mbc.py (OLS_core6, PCR_k, Ridge, ElasticNet, AdditiveSpline; MBC monthly/seasonal/annual x PSEUDO 50/500/2000 x UPPER 3/5 + regional). Selection used 2020-2021 area-weighted RMSE only; no 2022-2025 data. MBC validation RMSE 14.374 mm/week: foundational_validation_independent_comparison.csv. The full leaderboard (FULLGRID_VALIDATION_LEADERBOARD.csv) stayed on the HPC.");
}


// ================================================================= 5b. experiments that led to CatBoost
{
  const s = content("04 · EXPERIMENTS", "The experiments that led to CatBoost, in order", "Methods");
  const hdr = (t) => ({ text: t, options: { bold: true, color: H.white, fill: { color: H.deep } } });
  const b = (t) => ({ text: t, options: { bold: true } });
  s.addTable([
    [hdr("#"), hdr("Experiment"), hdr("Set-up"), hdr("Result, RMSE mm/week")],
    [b("E0"), "Statistical calibration", "OLS, PCR, ridge, elastic net, spline, 19 MBC variants; validate 2020–21", "MBC monthly, λ 500, cap 3: 14.37"],
    [b("E1"), "MBC + Atmos37 CatBoost (before LOYO)", "37 inputs, 378 trees, depth 7; train 2008–19", "Validation 14.05, r 0.93; no independent test"],
    [b("E2"), "CatBoost vs LightGBM, LOYO targets", "24 inputs (17 PCs); train 2005–19", "Valid. 14.28 vs 14.38; test 15.20 vs 15.24 (raw 17.27)"],
    [b("E3"), "Issue policies", "Full, α = 0.75 blend, MAM-protected, MBC only", "Full CatBoost lowest: 15.20"],
    [b("E4"), "Final refit (operational)", "MBC, PCA, CatBoost on 2005–21", "15.16; −0.048 vs pre-refit (not significant)"],
    [b("E5"), "Ensemble probabilities", "ROC, reliability, Brier, CRPS of raw ECMWF", "Baseline for calibrated chances"],
    [b("E6"), "Live verification", "17 weeks, Aug–Nov 2026", "MBC + AI/ML 9.2% below raw"],
  ], { x: 0.6, y: 1.4, w: 12.15, colW: [0.6, 3.3, 4.55, 3.7], fontSize: 13, rowH: 0.6, valign: "middle", border: { type: "solid", color: H.line, pt: 0.75 }, margin: [2, 6, 2, 6] });
  txt(s, "E1 showed CatBoost could add skill over MBC but used many inputs and no independent test. E2 cut the inputs to 24, added LOYO targets and a held-out 2022–2024 test: CatBoost beat LightGBM on both.", { x: 0.6, y: 6.3, w: 12.15, h: 0.7, fontSize: 14, bold: true, color: H.deep });
  s.addNotes("[1:00] E1: docs/hpc_integration_report.md (MBC_EXPERIMENT_20261005; 378 trees depth 7; validation RMSE 14.05, MAE 6.97, bias -0.29, r 0.93; E1 MBC R = clip(O/max(F,0.1), 0.05, 20)). E2: foundational_validation_independent_comparison.csv. E3: T01_independent_regional_metrics.csv. E4: PAIRED_OLD_VS_REFIT_MONTH_BLOCK_CI.csv.");
}

// ================================================================= 6. four ML models
{
  const s = content("04 · MACHINE LEARNING", "Four tree-based models, explained as a forecaster would", "Methods");
  const cards = [
    { name: "Random forest", color: H.blue, tint: H.bluePale, kind: "rf",
      analogy: "A committee of forecasters, each shown a random set of past weeks and predictors. The forecast is their average.",
      formula: "f(x) = (1/B) Σ T_b(x)",
      apart: "Deep trees grown independently (bagging). Lowers variance, but no tree corrects another's mistakes.", score: "Run in early experiments" },
    { name: "XGBoost", color: H.purple, tint: H.purplePale, kind: "seq",
      analogy: "One forecaster correcting the guidance step by step, using how fast and how sharply the error changes.",
      formula: "Fₜ = Fₜ₋₁ + η hₜ;  w* = −G / (H + λ)",
      apart: "Boosting with the gradient and curvature of the loss, plus regularisation. Trees grow level by level.", score: "Run in early experiments" },
    { name: "LightGBM", color: H.mbc, tint: H.amberPale, kind: "leaf",
      analogy: "The same step-by-step corrections, but it fixes the worst region first and bins values to work fast.",
      formula: "split the leaf with the largest gain",
      apart: "Leaf-wise growth and histograms: the fastest on 600 M rows, but can overfit small samples.", score: "Valid. 14.38 · Test 15.24" },
    { name: "CatBoost (chosen)", color: H.green, tint: H.pale, kind: "sym",
      analogy: "Every forecaster must ask the same question of all cells at each level, and learns only from earlier cases.",
      formula: "300 symmetric trees, depth 6 (64 leaves), η 0.05",
      apart: "Symmetric trees and ordered boosting resist overfitting. Lowest validation and test error.", score: "Valid. 14.28 · Test 15.20" },
  ];
  cards.forEach((c, i) => {
    const x = 0.6 + i * 3.06, y = 1.4, w = 2.9;
    block(s, { x, y, w, h: 5.2, title: c.name, color: c.color, tint: c.tint, name: c.name });
    drawTree(s, c.kind, x + 0.2, y + 0.6, w - 0.4, 0.8, c.color);
    txt(s, c.analogy, { x: x + 0.16, y: y + 1.5, w: w - 0.32, h: 1.25, fontSize: 13, italic: true });
    txt(s, c.formula, { x: x + 0.16, y: y + 2.8, w: w - 0.32, h: 0.55, fontSize: 13, bold: true, color: H.deep });
    txt(s, c.apart, { x: x + 0.16, y: y + 3.38, w: w - 0.32, h: 1.2, fontSize: 13 });
    chip(s, x + 0.16, y + 4.62, w - 0.32, 0.42, c.score, H.white, c.color, 12);
  });
  txt(s, "RMSE in mm/week: validation 2020–2021, independent test 2022–2024. All four learn the error left by MBC from the same inputs.", { x: 0.6, y: 6.68, w: 12.1, h: 0.32, fontSize: 12, color: H.muted });
  s.addNotes("[1:30] CatBoost and LightGBM scores: PRE_REFIT_INDEPENDENT_2022_2024_20261025/tables/foundational_validation_independent_comparison.csv (14.280/15.204 and 14.383/15.238). Random forest and XGBoost scores are not in the frozen verification tables: quote them from the experiment notes if asked. CatBoost settings: FINAL_REFIT_MODEL_MANIFEST.json (300 iterations, depth 6, learning rate 0.05, l2_leaf_reg 8, RMSE loss).");
}


// ================================================================= 6b. ML flowchart
{
  const s = content("04 · ML WORKFLOW", "The machine-learning workflow, as a flowchart", "Methods");
  const node = (x, y, w, h, t, c, col = H.white) => chip(s, x, y, w, h, t, c, col, 13);
  const down = (x, y) => s.addShape(pres.shapes.DOWN_ARROW, { x, y, w: 0.26, h: 0.3, fill: { color: H.clim }, line: { color: H.clim } });
  // row 1: data
  node(0.6, 1.45, 2.3, 0.75, "ECMWF reforecasts 2005–2024", H.raw);
  node(0.6, 2.45, 2.3, 0.75, "CHIRPS Week-2 totals", H.raw);
  arrow(s, 3.0, 2.05);
  node(3.45, 1.85, 2.2, 0.95, "Preprocess: totals, mean, spread, regrid, mask", H.deep);
  arrow(s, 5.75, 2.2);
  node(6.2, 1.45, 2.4, 0.75, "MBC factors, LOYO by year", H.mbc);
  node(6.2, 2.45, 2.4, 0.75, "PCA: 30 upper-air → 17 PCs", H.mbc);
  arrow(s, 8.7, 2.05);
  node(9.15, 1.85, 3.6, 0.95, "24 inputs; target y = CHIRPS − LOYO MBC", H.green);
  down(10.82, 2.9);
  // row 2: model choice
  node(9.15, 3.3, 3.6, 0.85, "Train tree models on 2005–2019 (CatBoost, LightGBM; RF and XGBoost earlier)", H.green);
  s.addShape(pres.shapes.LEFT_ARROW, { x: 8.7, y: 3.6, w: 0.32, h: 0.26, fill: { color: H.clim }, line: { color: H.clim } });
  s.addShape(pres.shapes.DIAMOND, { x: 6.2, y: 3.32, w: 2.4, h: 1.0, fill: { color: H.amber }, line: { color: H.amber } });
  s.addText("Lowest RMSE on 2020–2021?", { x: 6.35, y: 3.32, w: 2.1, h: 1.0, fontSize: 13, bold: true, color: H.white, align: "center", valign: "middle", margin: 0, isTextBox: true });
  s.addShape(pres.shapes.LEFT_ARROW, { x: 5.75, y: 3.6, w: 0.4, h: 0.26, fill: { color: H.clim }, line: { color: H.clim } });
  node(3.45, 3.3, 2.2, 0.85, "CatBoost and issue policy chosen", H.deep);
  down(4.42, 4.25);
  // row 3: test, refit, operate
  node(3.45, 4.65, 2.2, 0.85, "One test on 2022–2024", H.blue);
  arrow(s, 5.75, 4.95);
  node(6.2, 4.65, 2.4, 0.85, "Refit on 2005–2021", H.deep);
  arrow(s, 8.7, 4.95);
  node(9.15, 4.65, 3.6, 0.85, "Weekly: Ŷ = max(MBC + ŷ, 0), verified each week", H.hyb);
  block(s, { x: 0.6, y: 3.45, w: 2.55, h: 2.05, title: "Fallback", color: H.red, tint: H.redPale, size: 13, body: "Upper air late: issue MBC and say so. Nothing is filled in." });
  txt(s, "Validation years choose; the test years are used once; the refit learns from every year up to 2021.", { x: 0.6, y: 5.85, w: 12.15, h: 0.5, fontSize: 15, bold: true, color: H.deep });
  s.addNotes("[0:50] Walk the arrows: data, preprocessing, MBC with leave-one-year-out and PCA, the residual target, the four tree models, the choice on 2020-2021, the single 2022-2024 test, the refit and weekly operation.");
}

/** Small tree glyphs: what each algorithm's trees look like. */
function drawTree(s, kind, x, y, w, h, color) {
  const dot = (cx, cy, r = 0.07, c = color) => s.addShape(pres.shapes.OVAL, { x: cx - r, y: cy - r, w: 2 * r, h: 2 * r, fill: { color: c }, line: { color: c } });
  const ln = (x1, y1, x2, y2) => s.addShape(pres.shapes.LINE, { x: Math.min(x1, x2), y: y1, w: Math.abs(x2 - x1) || 0.001, h: y2 - y1, line: { color, width: 1.25 }, flipH: x2 < x1 });
  const tri = (cx, top, spread, depth) => {
    const lv = [[cx]];
    for (let d = 1; d <= depth; d++) {
      const prev = lv[d - 1], next = [];
      prev.forEach((p) => { next.push(p - spread / 2 ** d, p + spread / 2 ** d); });
      lv.push(next);
    }
    const dy = h / (depth + 0.4);
    lv.forEach((row, d) => row.forEach((px, k) => {
      if (d > 0) { const parent = lv[d - 1][Math.floor(k / 2)]; ln(parent, top + (d - 1) * dy, px, top + d * dy); }
    }));
    lv.forEach((row, d) => row.forEach((px) => dot(px, top + d * dy)));
  };
  if (kind === "rf") { [0.18, 0.5, 0.82].forEach((f) => tri(x + w * f, y + 0.08, 0.38, 2)); }
  if (kind === "seq") {
    [0.15, 0.5, 0.85].forEach((f, i) => { tri(x + w * f, y + 0.08, 0.34, 2); if (i < 2) s.addShape(pres.shapes.RIGHT_ARROW, { x: x + w * f + 0.33, y: y + 0.3, w: 0.28, h: 0.16, fill: { color: H.clim }, line: { color: H.clim } }); });
  }
  if (kind === "leaf") {
    const cx = x + w / 2, dy = h / 3.4, t = y + 0.08;
    const pts = [[cx, t], [cx - 0.5, t + dy], [cx + 0.5, t + dy], [cx + 0.2, t + 2 * dy], [cx + 0.8, t + 2 * dy], [cx + 0.55, t + 3 * dy], [cx + 1.05, t + 3 * dy]];
    [[0, 1], [0, 2], [2, 3], [2, 4], [4, 5], [4, 6]].forEach(([a, b]) => ln(pts[a][0], pts[a][1], pts[b][0], pts[b][1]));
    pts.forEach((p) => dot(p[0], p[1]));
  }
  if (kind === "sym") { tri(x + w / 2, y + 0.08, 1.15, 3); }
}

// ================================================================= 7. hybrid model
{
  const s = content("04 · THE MBC + AI/ML MODEL", "MBC + AI/ML: the model learns only what MBC still misses", "Methods");
  const boxes = [["Raw ECMWF", H.raw], ["MBC", H.mbc], ["24 inputs", H.deep], ["CatBoost residual", H.green], ["Final rainfall", H.hyb]];
  boxes.forEach(([t, c], i) => { const x = 0.6 + i * 2.5; chip(s, x, 1.45, 2.05, 0.8, t, c, H.white, 15); if (i < 4) arrow(s, x + 2.1, 1.72); });
  block(s, {
    x: 0.6, y: 2.6, w: 5.2, h: 4.25, title: "How it works", color: H.deep,
    body: [
      { text: "Target:  y = O − MBC", options: { bold: true, fontSize: 16, color: H.deep, breakLine: true } },
      { text: "Model:  ŷ = Σₜ fₜ(x),  t = 1 … 300", options: { bold: true, fontSize: 16, color: H.deep, breakLine: true } },
      { text: "Issued:  Ŷ = max( MBC + ŷ, 0 )", options: { bold: true, fontSize: 16, color: H.deep, breakLine: true } },
      { text: " ", options: { fontSize: 8, breakLine: true } },
      { text: "In climate terms: a first guess plus the forecaster's adjustment, never negative rain. Asking ML only for MBC's error keeps the physics-based forecast in charge and makes the ML gain easy to measure.", options: { fontSize: 14 } },
    ],
  });
  const groups = [
    ["Rainfall (3)", "Ensemble mean and spread of Week-2 rainfall, and the MBC value", H.raw],
    ["Place and season (4)", "Latitude, longitude; day of year as sine and cosine", H.amber],
    ["Atmosphere (17)", "17 principal components of 15 upper-air fields × (mean, spread) at 850–200 hPa, fitted on training years only", H.green],
  ];
  s.addText("What the model uses today", { x: 6.15, y: 2.6, w: 6.5, h: 0.4, fontSize: 16, bold: true, color: H.deep, margin: 0, isTextBox: true });
  groups.forEach(([t, d, c], i) => {
    const y = 3.15 + i * 1.12;
    chip(s, 6.15, y, 2.2, 0.9, t, c, H.white, 14);
    txt(s, d, { x: 8.55, y: y + 0.05, w: 4.2, h: 0.9, fontSize: 14, valign: "middle" });
  });
  txt(s, "Nothing on the ocean, the MJO, soil moisture or terrain: the reason for the driver experiment.", { x: 6.15, y: 6.5, w: 6.6, h: 0.4, fontSize: 14, bold: true, color: H.mbc });
  s.addNotes("[1:00] Formulas: climate_engine/models/hybrid7_pc17.py (residual = CatBoost(24 predictors); final = max(MBC + residual, 0)). Feature schema: artifacts/bundles/ICPAC_WEEK2_CATBOOST_FINAL_REFIT_2005_2021.");
}

// ================================================================= 8. LOYO and refit
{
  const s = content("05 · HONEST TESTING", "Leave-one-year-out (LOYO) and the final refit", "Methods");
  s.addText("LOYO: each year's MBC factor is fitted without that year", { x: 0.6, y: 1.4, w: 7.0, h: 0.38, fontSize: 16, bold: true, color: H.deep, margin: 0, isTextBox: true });
  for (let i = 0; i < 17; i++) {
    const year = 2005 + i, x = 0.6 + i * 0.41, on = year === 2012;
    chip(s, x, 1.95, 0.37, 0.95, String(year).slice(2), on ? H.amber : H.green, H.white, 12);
  }
  txt(s, [{ text: "Target year (2012): ", options: { bold: true, color: H.amber } }, { text: "its residual O − MBC uses an MBC factor fitted on the other 16 years. Repeat for every year." }], { x: 0.6, y: 3.05, w: 7.0, h: 0.7 });
  block(s, {
    x: 0.6, y: 3.9, w: 7.0, h: 2.95, title: "Why LOYO", color: H.amber, tint: H.amberPale,
    body: bullets([
      "If a year's own rain built its MBC factor, MBC would look better on that year than it ever does live.",
      "The residuals would be too small, and CatBoost would learn to trust MBC too much: leakage.",
      "With LOYO, training residuals look like real forecast errors, so the learned correction holds on new weeks.",
    ], { paraSpaceAfter: 8 }),
  });
  block(s, {
    x: 7.9, y: 1.4, w: 4.85, h: 3.1, title: "The final refit", color: H.deep,
    body: bullets([
      "MBC, PCA and CatBoost refitted on all of 2005–2021: the operational model.",
      "Its 2022–2024 scores are a retrospective comparison: those years helped choose the policy.",
    ], { paraSpaceAfter: 8 }),
  });
  stat(s, 7.95, 4.75, 4.8, "−0.048 mm/week", "refit minus pre-refit RMSE, 95% CI −0.105 to +0.020 (paired month-block bootstrap): no worse, and kept because it learned from every year to 2021.", H.deep);
  s.addNotes("[1:15] LOYO: provenance/canonical_prepare_fullgrid_ml.py ('2005-2019 train: LOYO MBC by year') and refit_pipeline.py (target 'CHIRPS minus LOYO MBC'). LOYO prevents leakage in the residual target; it is not a cross-validation of CatBoost's settings. Refit CI: PAIRED_OLD_VS_REFIT_MONTH_BLOCK_CI.csv.");
}

// ================================================================= 9. results
pres.addSection({ title: "Results" });
{
  const s = content("06 · RESULTS, 2022–2024", "12% lower error than raw ECMWF, most of it from MBC", "Results");
  s.addChart(pres.charts.BAR, [{ name: "RMSE", labels: ["Raw ECMWF", "Climatology", "MBC", "MBC + AI/ML"], values: [17.269, 17.519, 15.364, 15.156] }], Object.assign({
    x: 0.6, y: 1.35, w: 6.6, h: 5.3, barDir: "col", chartColors: [H.raw, H.clim, H.mbc, H.hyb], varyColors: true,
    showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "0.00", valAxisMinVal: 14, valAxisMaxVal: 18,
    showTitle: true, title: "RMSE, mm/week (lower is better), 551 forecasts", showLegend: false,
    valGridLine: { color: H.line, size: 0.5 }, catGridLine: { style: "none" },
  }, chartText));
  const hdr = (t) => ({ text: t, options: { bold: true, color: H.white, fill: { color: H.deep }, align: "center" } });
  const row = (a, ...v) => [{ text: a, options: { bold: true } }, ...v.map((x) => ({ text: x, options: { align: "center" } }))];
  s.addTable([
    [hdr("Model"), hdr("RMSE"), hdr("MAE"), hdr("Bias"), hdr("ACC")],
    row("MBC + AI/ML", "15.16", "7.53", "−0.27", "0.50"),
    row("MBC", "15.36", "7.67", "−0.26", "0.48"),
    row("Raw ECMWF", "17.27", "9.07", "+1.63", "0.37"),
    row("Climatology", "17.52", "8.74", "−1.33", "–"),
  ], { x: 7.5, y: 1.45, w: 5.25, colW: [1.65, 0.9, 0.9, 0.9, 0.9], fontSize: 14, color: H.ink, rowH: 0.48, border: { type: "solid", color: H.line, pt: 0.75 } });
  block(s, {
    x: 7.5, y: 4.15, w: 5.25, h: 2.7, title: "Reading the numbers", color: H.amber, tint: H.amberPale,
    body: bullets([
      "MBC removes the wet bias (+1.63 → −0.26 mm/week): 11.0% of the 12.2%.",
      "AI/ML adds 1.4% over MBC and the best anomaly correlation (0.50).",
      "Wet weeks are told apart better: ROC area at 25 mm 0.951, against 0.937 raw.",
    ], { paraSpaceAfter: 6 }),
  });
  s.addNotes("[1:00] GLOBAL_METRICS.csv of the refit retrospective. The y-axis starts at 14 mm/week: say so. ROC AUC at 25 mm/week: figures/07_ROC_25mm.png (raw 0.937, MBC 0.949, CatBoost + MBC 0.951).");
}

// ================================================================= 10. maps
{
  const s = content("06 · VERIFICATION MAPS", "Where the error falls: RMSE maps, 2022–2024", "Results");
  const maps = [["rmse_raw.png", "RMSE: raw ECMWF"], ["rmse_mbc.png", "RMSE: MBC"], ["rmse_cat.png", "RMSE: MBC + AI/ML"], ["gain_raw.png", "Error reduction over raw (red = better)"]];
  maps.forEach(([f, c], i) => image(s, f, 0.6 + i * 3.06, 1.4, 2.9, 2.88, c, c + " map, 2022-2024"));
  block(s, {
    x: 0.6, y: 4.85, w: 12.15, h: 2.0, title: "What the maps show",
    body: bullets([
      "Errors are largest where it rains most: western Ethiopia, the Lake Victoria basin, Burundi, Rwanda and southern Tanzania.",
      "The biggest gains over raw ECMWF are over South Sudan, the Ethiopian highlands and Sudan's rain belt; a few blue patches remain where raw ECMWF was already better.",
    ], { paraSpaceAfter: 6 }),
  });
  s.addNotes("[1:00] Maps: FINAL_REFIT_RETROSPECTIVE_2022_2024_20261027/maps/02_RMSE_RAW_MBC_REFIT_POLICIES.png and 05_ADDED_VALUE_OVER_RAW.png (panels cropped). mm/week, 551 cases, 0.05 degree.");
}

// ================================================================= 11. seasons and extremes
{
  const s = content("06 · SEASONS AND EXTREMES", "Where the model helps most, and where it still struggles", "Results");
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  s.addChart(pres.charts.LINE, [
    { name: "Raw ECMWF", labels: months, values: [0.14, 0.11, 0.18, 0.01, 0.15, -0.29, -0.57, -0.59, -0.55, 0.16, 0.22, 0.28] },
    { name: "MBC", labels: months, values: [0.22, 0.24, 0.3, 0.19, 0.25, 0.13, 0.03, 0.0, 0.09, 0.35, 0.3, 0.28] },
    { name: "MBC + AI/ML", labels: months, values: [0.22, 0.26, 0.28, 0.21, 0.29, 0.15, 0.1, 0.13, 0.12, 0.35, 0.31, 0.32] },
  ], Object.assign({
    x: 0.6, y: 1.35, w: 7.3, h: 5.5, chartColors: [H.raw, H.mbc, H.hyb], lineSize: 2.5, lineDataSymbolSize: 6,
    showTitle: true, title: "Skill against climatology by month (above 0 = better)", showLegend: true, legendPos: "b",
    valGridLine: { color: H.line, size: 0.5 }, catGridLine: { style: "none" }, valAxisLabelFormatCode: "0.0",
  }, chartText));
  stat(s, 8.3, 1.4, 4.4, "Jun–Sep", "raw ECMWF is worse than climatology; the AI/ML layer adds most here (+0.03 to +0.13)", H.hyb);
  stat(s, 8.3, 3.2, 4.4, "−69 mm", "bias in weeks with 100 mm or more observed: extremes are still far too low", H.red);
  stat(s, 8.3, 5.0, 4.4, "+2.8 mm", "bias in near-dry weeks (0–1 mm): drizzle where none fell", H.mbc);
  s.addNotes("[1:00] Skill: DETERMINISTIC_SKILL_AGAINST_REFIT_CLIMATOLOGY.csv (months are initialisation months). Extremes: RAINFALL_INTENSITY_METRICS.csv (CatBoost bias -69.10 mm/week for observed >= 100; +2.84 for 0-1 mm). Squared-error training pulls extremes towards the mean: one reason for probabilistic models and more drivers.");
}

// ================================================================= 12. probabilities and live weeks
{
  const s = content("06 · RELIABILITY AND LIVE WEEKS", "Probabilities from the ensemble, and the first live weeks", "Results");
  image(s, "09_ORIGINAL_ECMWF_RELIABILITY_25mm.png", 0.6, 1.4, 3.9, 3.34, "Reliability, raw ECMWF, 25 mm/week or more", "Reliability diagram");
  image(s, "07_ROC_25mm.png", 4.75, 1.4, 3.72, 3.34, "ROC, 25 mm/week or more", "ROC curves");
  block(s, {
    x: 0.6, y: 5.15, w: 7.87, h: 1.7, title: "Reading the two charts",
    body: "Points below the diagonal: when ECMWF gives a high chance of 25 mm or more, it rains less often than that. The corrected forecasts separate wet from dry weeks slightly better (ROC area 0.951 against 0.937).",
  });
  block(s, {
    x: 8.75, y: 1.4, w: 4.0, h: 5.45, title: "Live forecasts, Aug–Nov 2026", color: H.blue, tint: H.bluePale,
    body: [
      { text: "−9.2%", options: { bold: true, fontSize: 40, color: H.blue, breakLine: true } },
      { text: "RMSE of MBC + AI/ML against raw ECMWF over 17 verified weeks (95% interval −12.8% to −5.8%).", options: { fontSize: 14, breakLine: true } },
      { text: " ", options: { fontSize: 8, breakLine: true } },
      { text: "Each live week is now verified automatically against CHIRPS, ARC 2.0, RFE 2.0 and GPM IMERG, using whichever have arrived.", options: { fontSize: 14 } },
    ],
  });
  s.addNotes("[0:50] Figures: 09_ORIGINAL_ECMWF_RELIABILITY_25mm.png, 07_ROC_25mm.png. Live weeks: the verification summary of 6 Nov 2026 (17 weeks, observed by CHIRPS, else ARC 2.0, else RFE 2.0). Both corrections still ran wet in those weeks.");
}

// ================================================================= 13. drivers
pres.addSection({ title: "Drivers and the service" });
{
  const s = content("07 · CLIMATE DRIVERS", "Why add drivers, and where the 245-driver download stands", "Drivers and the service");
  block(s, {
    x: 0.6, y: 1.4, w: 4.4, h: 4.15, title: "Why the 24 inputs are not enough", color: H.mbc, tint: H.amberPale,
    body: bullets([
      "No ocean state (ENSO, IOD, Somali coast SST).",
      "No MJO, the main source of Week-2 skill.",
      "No soil moisture or recent rain.",
      "1.5° fields: no lakes, coasts or mountains.",
      "Extremes 69 mm/week too low.",
    ], { paraSpaceAfter: 7 }),
  });
  const groups = ["Atmospheric dynamics (55)", "Moisture transport (35)", "Rainfall and ensemble (40)", "Antecedent rain and land (25)", "Ocean and climate indices (25)", "Regional circulation (20)", "Geography and climatology (20)", "Time and space transforms (15)", "Cloud microphysics (5)", "Cloud and surface diag. (5)"];
  const data = [
    { name: "Ready", labels: groups, values: [36, 19, 37, 25, 22, 2, 19, 14, 0, 1] },
    { name: "Data ready, method needed", labels: groups, values: [0, 0, 0, 0, 0, 16, 1, 0, 0, 0] },
    { name: "Downloading", labels: groups, values: [1, 6, 0, 0, 0, 0, 0, 1, 0, 1] },
    { name: "Missing", labels: groups, values: [18, 10, 3, 0, 3, 2, 0, 0, 5, 3] },
  ];
  s.addChart(pres.charts.BAR, data, Object.assign({
    x: 5.25, y: 1.35, w: 7.5, h: 4.3, barDir: "bar", barGrouping: "stacked", chartColors: [H.green, H.amber, H.blue, H.clim],
    showTitle: true, title: "245 drivers by group: 175 ready, 17 need a method, 9 downloading, 44 missing", showLegend: true, legendPos: "b",
    catAxisOrientation: "maxMin", valGridLine: { color: H.line, size: 0.5 }, catGridLine: { style: "none" }, catAxisLabelFontSize: 11,
  }, chartText));
  const tiles = [["186/186", "CAPE, skin temp., TCW, SM20"], ["60/186", "925 hPa u, v, q, t, gh"], ["17/186", "Convective precipitation"], ["Started", "Mean sea-level and surface pressure"], ["Queued", "Vertical velocity, 6 levels"]];
  s.addText("ECMWF reforecast downloads on the HPC, 23 Nov 2026 (files per cycle set)", { x: 0.6, y: 5.75, w: 12, h: 0.32, fontSize: 13, bold: true, color: H.deep, margin: 0, isTextBox: true });
  tiles.forEach(([big, lab], i) => {
    const x = 0.6 + i * 2.45;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 6.1, w: 2.3, h: 0.85, fill: { color: H.pale }, line: { color: H.pale }, rectRadius: 0.08 });
    s.addText(big, { x: x + 0.12, y: 6.12, w: 2.06, h: 0.42, fontSize: 18, bold: true, color: i === 0 ? H.green : H.deep, margin: 0, isTextBox: true });
    s.addText(lab, { x: x + 0.12, y: 6.52, w: 2.1, h: 0.4, fontSize: 11, color: H.muted, margin: 0, isTextBox: true });
  });
  s.addNotes("[1:15] Readiness check on the HPC, 23 Nov 2026 (feature_dependencies_245.csv against the files present). The groups follow the 245-predictor catalogue (79 names recovered from earlier work, 166 proposed). Download counts from ~/status.sh at 14:28 EAT on 23 Nov. Plan: keep a group only if it lowers RMSE and CRPS under leave-one-year-out validation (SHAP and grouped ablation). The biggest blockers are IVT (7 drivers) and the 925 hPa fields.");
}

// ================================================================= 14. web service
{
  const s = content("08 · FROM RESEARCH TO OPERATIONS", "The weekly MBC + AI/ML service", "Drivers and the service");
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.6, y: 1.4, w: 6.9, h: 4.55, fill: { color: H.pale }, line: { color: H.line }, rectRadius: 0.08 });
  s.addImage({ path: A("forecast.png"), x: 0.75, y: 1.55, w: 6.6, h: 4.125, altText: "Forecast page of the web service" });
  s.addText("Forecast page (local test run of 22 Nov): raw, MBC and MBC + AI/ML layers", { x: 0.6, y: 6.0, w: 6.9, h: 0.3, fontSize: 12, color: H.muted, margin: 0, isTextBox: true });
  const steps = [
    ["Sunday ECMWF run", "downloaded and checked"],
    ["Forecast package", "raw, MBC, MBC + AI/ML; checksums"],
    ["Bulletin draft", "AI-written, every figure checked; emailed to the forecaster"],
    ["Review and publish", "forecaster edits, then approves"],
    ["Translate", "into any language, at any time"],
    ["Verify", "against CHIRPS, ARC 2.0, RFE 2.0, IMERG"],
  ];
  steps.forEach(([t, d], i) => {
    const y = 1.4 + i * 0.78;
    s.addShape(pres.shapes.OVAL, { x: 7.85, y: y + 0.08, w: 0.5, h: 0.5, fill: { color: H.green }, line: { color: H.green } });
    s.addText(String(i + 1), { x: 7.85, y: y + 0.08, w: 0.5, h: 0.5, fontSize: 15, bold: true, color: H.white, align: "center", valign: "middle", margin: 0, isTextBox: true });
    s.addText([{ text: t, options: { bold: true, breakLine: true } }, { text: d, options: { color: H.muted } }], { x: 8.5, y, w: 4.25, h: 0.7, fontSize: 14, margin: 0, isTextBox: true, valign: "middle" });
  });
  txt(s, "API on Hugging Face, website on Vercel; site in 6 languages, Copilot in 12, including Shona.", { x: 7.85, y: 6.2, w: 4.9, h: 0.7, fontSize: 13, bold: true, color: H.deep });
  s.addNotes("[1:00] Live site: icpac-ml-ai-product-three.vercel.app. Screens from a local test run. The frontend computes nothing scientific: every number comes from the API. The service moved from Azure to Hugging Face (API) and Vercel (website) in November 2026.");
}

// ================================================================= 15. copilot
{
  const s = content("08 · THE COPILOT", "The Forecaster Copilot: an agent that answers from the forecast", "Drivers and the service");
  chip(s, 0.6, 1.6, 2.2, 1.0, "Forecaster's question", H.blue, H.white, 14);
  arrow(s, 2.9, 1.97);
  chip(s, 3.3, 1.45, 2.6, 1.3, "Language model (agent)", H.deep, H.white, 15);
  arrow(s, 6.0, 1.97);
  chip(s, 6.4, 1.6, 2.4, 1.0, "Answer, figures checked", H.green, H.white, 14);
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.6, y: 3.05, w: 8.2, h: 2.3, fill: { color: H.pale }, line: { color: H.pale }, rectRadius: 0.08 });
  s.addText("18 read-only tools the agent calls", { x: 0.8, y: 3.12, w: 7, h: 0.38, fontSize: 15, bold: true, color: H.deep, margin: 0, isTextBox: true });
  const tools = ["Forecast", "Country", "Compare countries", "Verification", "Seasonal skill", "Bulletin", "Revise bulletin", "Translate", "Monitoring", "Data sources", "Model info", "Map", "Forecast weeks", "Uploaded model", "References", "Web search", "Wikipedia", "Read a web page"];
  tools.forEach((t, i) => chip(s, 0.8 + (i % 6) * 1.32, 3.6 + Math.floor(i / 6) * 0.56, 1.24, 0.46, t, H.white, H.deep, 11));
  block(s, {
    x: 0.6, y: 5.5, w: 8.2, h: 1.38, title: "The idea", color: H.amber, tint: H.amberPale, size: 14,
    body: "Grounding through tool calls: numbers come from the service's own tools, never from the model's memory. An answer whose figures are not in the tool results is rejected.",
  });
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 9.1, y: 1.4, w: 3.65, h: 5.48, fill: { color: H.pale }, line: { color: H.line }, rectRadius: 0.08 });
  s.addImage({ path: A("copilot.png"), x: 9.2, y: 1.5, w: 3.45, h: 2.16, altText: "Copilot page" });
  txt(s, bullets([
    "Answers in 12 languages, Shona included",
    "Compares another model's uploaded forecast",
    "Open-weight models (Groq) or any OpenAI-compatible or self-hosted model",
  ], { paraSpaceAfter: 6 }), { x: 9.25, y: 3.85, w: 3.4, h: 2.9, fontSize: 14 });
  s.addNotes("[0:50] chatbot/agent.py: 18 tools (get_forecast, get_country_forecast, compare_countries, get_verification, get_seasonal_skill, get_weekly_bulletin, revise_bulletin, translate_bulletin, get_rainfall_monitoring, get_data_sources, get_model_info, show_map, list_forecast_weeks, compare_uploaded_forecast, search_references, search_web, search_wikipedia, read_web_page). General questions are answered from the model's knowledge; only ICPAC figures must come from tools.");
}

// ================================================================= 16. next models
pres.addSection({ title: "What comes next" });
{
  const s = content("09 · NEXT MODELS", "Models worth trying next, and why they can beat the four trees", "What comes next");
  const cards = [
    ["Probabilistic CatBoost", "Quantile or censored-gamma (CSGD) outputs: chances of heavy rain, scored with CRPS and reliability.", H.green, H.pale],
    ["U-Net post-processing", "Sees the whole map: rain shadows, lakes, coasts and displaced rain bands that a per-cell tree cannot.", H.blue, H.bluePale],
    ["cGAN or diffusion", "Many realistic rainfall maps with local extremes; builds on ICPAC's own cGAN (SEWAA).", H.purple, H.purplePale],
    ["Distributional network", "A neural network predicting CSGD parameters per cell (Rasp & Lerch 2018): probabilistic by design.", H.deep, H.pale],
    ["Analog ensemble", "The past reforecasts most like today, and what then fell: a strong, explainable baseline.", H.mbc, H.amberPale],
    ["AI weather models as inputs", "AIFS ENS, GenCast and Aurora Week-2 fields as extra predictors, verified like every forecast.", H.amber, H.amberPale],
  ];
  cards.forEach(([t, d, c, tint], i) => {
    const x = 0.6 + (i % 3) * 4.1, y = 1.4 + Math.floor(i / 3) * 2.05;
    block(s, { x, y, w: 3.95, h: 1.88, title: t, color: c, tint, body: d });
  });
  block(s, { x: 0.6, y: 5.6, w: 12.15, h: 1.28, title: "One fair test for all of them", color: H.deep, body: "Same 2005–2021 training with LOYO, same 2022–2024 test; scored with RMSE, CRPS, Brier at 50 and 200 mm/week and reliability. Keep only what beats MBC + AI/ML." });
  s.addNotes("[1:00] From docs/model_roadmap.md. Order of value for a small team: probabilities first (no new data needed), then whole-map models, then AI-model inputs. All are judged against the current MBC + AI/ML on CRPS, Brier scores at 50 and 200 mm/week and reliability.");
}

// ================================================================= 17. downscaling roadmap
{
  const s = content("09 · ROADMAP", "Bringing global AI models down to the ICPAC region", "What comes next");
  const phases = [
    ["1 · Use", "0–3 months", "AIFS ENS and GenCast Week-2 rain and fields as extra inputs to MBC + AI/ML; verify each like any forecast.", H.blue],
    ["2 · Downscale", "3–6 months", "Train a cGAN or diffusion model from 0.25° to ICPAC's 0.05° grid on CHIRPS and IMERG, with terrain and lakes as inputs.", H.green],
    ["3 · Fine-tune", "6–12 months", "Fine-tune AIFS with Anemoi, or Aurora and Prithvi WxC (LoRA), on East African rainfall and the new drivers.", H.purple],
    ["4 · Operate", "12 months +", "Run weekly on the ICPAC HPC GPUs; refit yearly; extend to Weeks 3–4 if skill allows.", H.amber],
  ];
  phases.forEach(([t, when, d, c], i) => {
    const x = 0.6 + i * 3.06;
    s.addShape(pres.shapes.CHEVRON, { x, y: 1.45, w: 2.95, h: 0.8, fill: { color: c }, line: { color: c } });
    s.addText(t, { x: x + 0.5, y: 1.45, w: 2.2, h: 0.8, fontSize: 16, bold: true, color: H.white, valign: "middle", margin: 0, isTextBox: true });
    s.addText(when, { x, y: 2.35, w: 2.9, h: 0.32, fontSize: 13, bold: true, color: c, margin: 0, isTextBox: true });
    txt(s, d, { x, y: 2.72, w: 2.85, h: 1.7, fontSize: 14 });
  });
  block(s, {
    x: 0.6, y: 4.5, w: 7.4, h: 2.35, title: "How the fine-tuning would work", color: H.deep,
    body: bullets([
      "Freeze the global model; train a new precipitation head on CHIRPS over the ICPAC domain.",
      "Validate leave-one-year-out, as for MBC; score with CRPS and RPSS against MBC + AI/ML.",
      "Keep the drivers that help: MJO, IOD, ENSO, soil moisture.",
    ], { paraSpaceAfter: 6 }),
  });
  block(s, {
    x: 8.3, y: 4.5, w: 4.45, h: 2.35, title: "Before starting", color: H.red, tint: H.redPale,
    body: "Check each model's licence: GenCast and Aurora weights are non-commercial and share-alike. Fine-tuning needs GPUs and ERA5-scale data handling.",
  });
  s.addNotes("[1:00] From docs/model_roadmap.md section 3: AIFS (CC BY 4.0, trained with Anemoi), GenCast (CC BY-NC-SA 4.0), Aurora (code MIT, weights CC BY-NC-SA 4.0, LoRA fine-tuning), Prithvi WxC (fine-tuning workflows for downscaling). Start fine-tuning only once the multi-model comparison shows which model helps most.");
}

// ================================================================= 18. bonus
{
  const s = content("BONUS", "ICPAC Minutes: meeting notes and slides from a recording", "What comes next");
  const steps = [
    ["Record or upload", "A Teams or Google Meet tab, or a file, up to 60 minutes"],
    ["Transcribe", "Whisper large-v3, English or Kiswahili"],
    ["Write", "Report in ICPAC's own template, plus a short deck"],
    ["Download", "Word, PDF, PowerPoint, subtitles"],
  ];
  steps.forEach(([t, d], i) => {
    const y = 1.45 + i * 1.02;
    chip(s, 0.6, y, 0.6, 0.6, String(i + 1), H.green, H.white, 16);
    s.addText([{ text: t, options: { bold: true, breakLine: true } }, { text: d, options: { color: H.muted } }], { x: 1.35, y: y - 0.06, w: 3.6, h: 0.8, fontSize: 14, margin: 0, isTextBox: true, valign: "middle" });
  });
  block(s, {
    x: 0.6, y: 5.6, w: 4.4, h: 1.28, title: "Why it helps ICPAC", color: H.amber, tint: H.amberPale, size: 13,
    body: "Many meetings: minutes and decks ready to review later.",
  });
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 5.3, y: 1.4, w: 7.45, h: 5.48, fill: { color: H.pale }, line: { color: H.line }, rectRadius: 0.08 });
  s.addImage({ path: A("mr_home_c.png"), x: 5.45, y: 1.52, w: 4.4, h: 2.54, altText: "ICPAC Minutes start page" });
  s.addImage({ path: A("mr_slides_c.png"), x: 7.4, y: 3.75, w: 5.2, h: 2.82, altText: "ICPAC Minutes slides view" });
  s.addText("Local run with a sample meeting", { x: 5.45, y: 6.58, w: 4, h: 0.28, fontSize: 11, color: H.muted, margin: 0, isTextBox: true });
  s.addNotes("[0:40] Repository joe254h/whisper-wolof-speech, branch ccr-2f1d0d8e-pcnwzp, folder meeting-recorder (runs at http://localhost:8000). Transcription with Groq or OpenAI Whisper, or locally with faster-whisper; reports through OpenRouter. The repository also holds my Whisper-small model fine-tuned for Wolof. The screenshot uses a sample meeting, not a real ICPAC meeting.");
}

// ================================================================= 19. acknowledgements
pres.addSection({ title: "Close" });
{
  const s = content("", "Acknowledgements", "Close");
  block(s, { x: 0.6, y: 1.4, w: 5.95, h: 1.75, title: "Supervision", body: "Dr. Masilin Gudoshava, Climate Forecaster (Machine Learning Expert) and Thematic Lead on Risk Assessment and Monitoring, for her guidance throughout." });
  block(s, { x: 0.6, y: 3.3, w: 5.95, h: 1.75, title: "Climate Prediction and Climate Services", color: H.blue, tint: H.bluePale, body: "The weekly forecast, climate data analysis and AI teams, for their technical guidance, data and feedback on the bulletin." });
  block(s, { x: 0.6, y: 5.2, w: 5.95, h: 1.66, title: "Every ICPAC department", color: H.amber, tint: H.amberPale, body: "For a warm welcome and support from colleagues across ICPAC." });
  block(s, {
    x: 6.85, y: 1.4, w: 5.9, h: 5.46, title: "The ICPAC HPC: how it made the thesis possible", color: H.deep,
    body: bullets([
      "Trained on all 647 million rows of the 0.05° grid, with no subsampling.",
      "Stored 20 years of inputs: ECMWF pressure levels (162 GB), CHIRPS (40 GB), ERA5-Land (27 GB), MODIS land cover (26 GB), OISST (10 GB).",
      "Ran MBC, PCA, CatBoost, the refit and verification as SLURM jobs on 12 nodes.",
      "Is now downloading and checking the 245 climate drivers.",
    ], { paraSpaceAfter: 9 }),
  });
  s.addNotes("[0:40] Storage: HPC data audit of 23 Nov 2026 on /scratch/njoel/s2s_master_data. Nodes: sinfo (serial 2, parallel 10).");
}

// ================================================================= 20. thanks
{
  const s = pres.addSlide({ masterName: "TITLE", sectionTitle: "Close" });
  n += 1;
  s.addText("“All models are wrong, but some are useful.”", { x: 2.0, y: 0.75, w: 10.7, h: 0.75, fontSize: 26, italic: true, color: H.deep, margin: 0, isTextBox: true, valign: "middle" });
  s.addText("George E. P. Box", { x: 2.0, y: 1.5, w: 10.7, h: 0.4, fontSize: 15, color: H.muted, margin: 0, isTextBox: true });
  s.addText("Thank you", { x: 0.6, y: 2.35, w: 12, h: 1.1, fontSize: 54, bold: true, color: H.deep, margin: 0, isTextBox: true });
  s.addText("Questions and discussion", { x: 0.6, y: 3.45, w: 12, h: 0.55, fontSize: 24, color: H.ink, margin: 0, isTextBox: true });
  const link = (label, text, url, y) => s.addText([
    { text: label, options: { bold: true, color: H.ink } },
    { text, options: { color: H.blue, hyperlink: { url } } },
  ], { x: 0.6, y, w: 12, h: 0.42, fontSize: 17, margin: 0, isTextBox: true });
  link("ICPAC Week-2 forecast service: ", "icpac-ml-ai-product-three.vercel.app", "https://icpac-ml-ai-product-three.vercel.app", 4.3);
  link("Its forecast API (Hugging Face): ", "huggingface.co/spaces/joe254h/icpac-api", "https://huggingface.co/spaces/joe254h/icpac-api", 4.8);
  link("ICPAC Minutes (meeting recorder): ", "github.com/Joe254h/whisper-wolof-speech", "https://github.com/Joe254h/whisper-wolof-speech/tree/ccr-2f1d0d8e-pcnwzp/meeting-recorder", 5.3);
  s.addText("Sangura J. Nyongesa · ICPAC internship 2026", { x: 0.6, y: 6.1, w: 12, h: 0.4, fontSize: 15, color: H.muted, margin: 0, isTextBox: true });
  s.addNotes("[0:15] Thank the audience. Appendix slides follow for questions: country scores, issue policies, live weeks.");
}

// ================================================================= appendix
pres.addSection({ title: "Appendix" });
{
  const s = content("APPENDIX", "Error by country, 2022–2024 (RMSE, mm/week)", "Appendix");
  const hdr = (t) => ({ text: t, options: { bold: true, color: H.white, fill: { color: H.deep }, align: "center" } });
  const rows = [["Tanzania", 23.75, 23.73, 25.2, 27.73], ["Kenya", 20.34, 20.44, 22.09, 23.82], ["Burundi", 20.12, 20.1, 23.31, 22.09], ["Rwanda", 19.23, 19.11, 24.97, 21.06], ["Uganda", 16.68, 16.87, 19.45, 18.95], ["Ethiopia", 16.35, 16.62, 19.09, 18.65], ["Somalia", 12.19, 12.23, 12.6, 14.85], ["South Sudan", 11.98, 12.47, 15.55, 13.22], ["Eritrea", 9.02, 9.63, 11.8, 10.27], ["Sudan", 6.16, 6.86, 9.43, 6.72], ["Djibouti", 4.69, 5.03, 11.23, 5.47]];
  const body = rows.map((r) => {
    const best = Math.min(...r.slice(1));
    return [{ text: r[0], options: { bold: true } }, ...r.slice(1).map((v) => ({ text: v.toFixed(2), options: { align: "center", bold: v === best, color: v === best ? H.green : H.ink } }))];
  });
  s.addTable([[hdr("Country"), hdr("MBC + AI/ML"), hdr("MBC"), hdr("Raw"), hdr("Climatology")], ...body], { x: 0.6, y: 1.4, w: 7.4, colW: [2.0, 1.4, 1.3, 1.3, 1.4], fontSize: 13, rowH: 0.42, border: { type: "solid", color: H.line, pt: 0.75 } });
  block(s, { x: 8.3, y: 1.4, w: 4.45, h: 2.4, title: "Dry north gains most", body: "Sudan, Djibouti, Eritrea and South Sudan: AI/ML cuts MBC's error by 0.3–0.7 mm/week." });
  block(s, { x: 8.3, y: 4.0, w: 4.45, h: 2.4, title: "Wet south is hardest", color: H.amber, tint: H.amberPale, body: "Tanzania, Kenya, Burundi and Rwanda have the largest errors; AI/ML and MBC are within 0.12 mm/week." });
  s.addNotes("COUNTRY_METRICS_NAMED.csv of the refit retrospective. Lowest value per row in green.");
}
{
  const s = content("APPENDIX", "Four ways to issue the final rainfall", "Appendix");
  const hdr = (t) => ({ text: t, options: { bold: true, color: H.white, fill: { color: H.deep } } });
  s.addTable([
    [hdr("Policy"), hdr("Final rainfall"), hdr("Pre-refit RMSE"), hdr("Refit RMSE")],
    ["Full CatBoost (in use)", "max(MBC + ŷ, 0)", "15.204", "15.156"],
    ["Global α = 0.75", "0.25 MBC + 0.75 max(MBC + ŷ, 0)", "15.210", "15.161"],
    ["MAM-protected", "MBC for March–May runs, otherwise the α blend", "15.271", "15.204"],
    ["MBC only (fallback)", "max(MBC, 0), when upper-air fields are late", "15.416", "15.364"],
  ], { x: 0.6, y: 1.5, w: 12.1, colW: [3.0, 5.3, 1.9, 1.9], fontSize: 14, rowH: 0.6, border: { type: "solid", color: H.line, pt: 0.75 } });
  txt(s, "RMSE in mm/week on 2022–2024 (551 forecasts). Lower is better.", { x: 0.6, y: 4.8, w: 12, h: 0.4, fontSize: 13, color: H.muted });
  s.addNotes("T01_independent_regional_metrics.csv (pre-refit) and GLOBAL_METRICS.csv (refit).");
}
{
  const s = content("APPENDIX", "Live forecasts, Aug–Nov 2026: 17 verified weeks", "Appendix");
  const hdr = (t) => ({ text: t, options: { bold: true, color: H.white, fill: { color: H.deep }, align: "center" } });
  const c = (t) => ({ text: t, options: { align: "center" } });
  s.addTable([
    [hdr("Layer"), hdr("RMSE (95% CI)"), hdr("MAE"), hdr("Bias"), hdr("r"), hdr("RMSE vs raw")],
    [{ text: "Raw", options: { bold: true } }, c("18.53 (15.8–22.3)"), c("12.14"), c("+6.56"), c("0.566"), c("–")],
    [{ text: "MBC", options: { bold: true } }, c("16.94 (14.3–20.8)"), c("9.98"), c("+2.63"), c("0.567"), c("−8.6% (−11.7 to −5.0)")],
    [{ text: "MBC + AI/ML", options: { bold: true } }, c("17.08 (14.4–20.9)"), c("10.13"), c("+3.09"), c("0.575"), c("−9.2% (−12.8 to −5.8)")],
  ], { x: 0.6, y: 1.5, w: 12.1, colW: [2.0, 2.6, 1.3, 1.3, 1.3, 3.6], fontSize: 14, rowH: 0.6, border: { type: "solid", color: H.line, pt: 0.75 } });
  txt(s, "mm/week; 95% bootstrap intervals over weeks. Observed by CHIRPS, else ARC 2.0, else RFE 2.0. Both corrections still ran wet in these weeks.", { x: 0.6, y: 4.2, w: 12, h: 0.6, fontSize: 13, color: H.muted });
  s.addNotes("Verification summary of 6 Nov 2026.");
}

(async () => {
  await pres.writeFile({ fileName: OUT });
  if (process.env.APPLY_THEME) {
    const { applyTheme } = require(process.env.APPLY_THEME);
    await applyTheme(OUT, THEME);
  }
  console.log("wrote", OUT, n, "slides");
})();
