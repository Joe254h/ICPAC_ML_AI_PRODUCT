/** Shapes returned by the operational forecast API (backend/app/api/forecasts.py). */
import type { Model } from "@/types";

export type Variant = "raw" | "mbc" | "hybrid";

export type OperationalModel = Model & {
  task?: string;
  experiment?: string;
  baseline?: string;
  family?: string;
  algorithm?: string;
  feature_count?: number;
  features?: string[];
  trees?: number | null;
  test_period?: string;
  test_status?: "untested" | "passed" | "failed";
  test_result?: {
    status: string;
    period: string;
    report: string;
    actor: string;
    recorded_at: string;
    metrics?: Record<string, number>;
  } | null;
  metrics?: Record<string, number>;
  metrics_scope?: string;
  artifact_checksums?: Record<string, string>;
  artifact_paths?: Record<string, string>;
  inference_test?: { status: string; timestamp: string; fixture?: string };
  validated?: boolean;
  deployment_date?: string | null;
  created_at?: string;
  registered_by?: string;
  descriptor?: { path: string; sha256: string; declared_by?: string };
  notes?: string;
};

export type CurrentModel = {
  role: "production" | "candidate";
  model: OperationalModel;
  note?: string;
};

export type ProductStatus = {
  status: "available" | "in_progress";
  reason?: string;
};

export type ForecastRun = {
  id: string;
  forecast_id: string;
  status: string;
  origin: "run" | "import";
  initialization: string;
  valid_start: string;
  valid_end: string;
  lead: string;
  generation_time: string;
  model_id: string;
  model_version: string;
  model_status: string;
  method: string;
  baseline: string;
  family: string;
  algorithm: string;
  input_label: string;
  synthetic: boolean;
  protected_test_period: boolean;
  verification_status: "available" | "unavailable";
  season?: string;
  created_at: string;
  created_by: string;
  notes: string[];
  /** Rainfall layers the forecast holds (hybrid only when the AI/ML inputs exist). */
  layers?: string[];
  primary_layer?: Variant;
  products?: Partial<Record<Variant, ProductStatus>>;
};

export type Stats = {
  mean_mm: number;
  median_mm: number;
  min_mm: number;
  max_mm: number;
};

export type CountryRow = {
  country: string;
  cell_count: number;
  raw: Stats;
  mbc: Stats;
  hybrid?: Stats;
  anomaly: { status: string; reason: string };
  category: { status: string; reason: string };
};

export type Metrics = {
  mae: number;
  rmse: number;
  bias: number;
  correlation: number | null;
  sample_count: number;
  forecast_mean: number;
  observed_mean: number;
  cases?: number;
};

export type Verification = {
  status: "available" | "unavailable";
  reason?: string;
  required?: string;
  season?: string;
  use?: string;
  scope?: string;
  protected_test_period?: boolean;
  observation?: { file: string; sha256: string };
  domain?: Partial<Record<Variant, Metrics>>;
  countries?: Record<string, Partial<Record<Variant, Metrics>>>;
};

export type Interpretation = {
  domain_mean_mm: Partial<Record<Variant | "residual", number>>;
  primary_layer?: Variant;
  layers?: string[];
  method: { label: string; description: string; baseline: string };
  model: {
    model_id: string;
    version: string;
    status: string;
    role: string;
    independent_test: string;
  };
  input: { label: string; synthetic: boolean };
  anomaly: { status: string; missing_dependency: string };
  category: { status: string; missing_dependency: string };
  caveats: string[];
};

export type Provenance = Record<string, unknown> & {
  model_id: string;
  model_version: string;
  model_checksum: string;
  mbc_artifact_checksum: string;
  feature_schema: string;
  feature_schema_checksum: string;
  forecast_initialization: string;
  forecast_valid_start: string;
  forecast_valid_end: string;
  generation_time: string;
  grid_definition: { shape: number[]; resolution?: number } & Record<
    string,
    unknown
  >;
  domain_definition: { name: string; cells: number; mask_sha256: string };
  input_source: {
    source: string;
    mode: string;
    format: string;
    inputs: { path: string }[];
  };
  input_label: string;
  software_version: { package: string; git_commit: string };
  ensemble_members: number;
  mbc_month: number;
  configuration_overrides: Record<string, { value: unknown; reason: string }>;
  model: { algorithm: string; family: string; baseline: string; trees: number };
};

export type ForecastDetail = ForecastRun & {
  map_style?: string;
  bulletin_generator?: BulletinStatus["generator"];
  manifest: {
    labels: string[];
    files: Record<string, string>;
    missing_dependencies: Record<string, string>;
  };
  provenance: Provenance;
  model: Partial<OperationalModel>;
  countries: CountryRow[];
  verification: Verification;
  interpretation: Interpretation;
  maps: Record<string, string>;
  files: Record<string, string>;
  overlays?: Partial<Record<Variant, string>>;
  overlay_bounds?: [number, number, number, number];
};

export type Seasonal = {
  model_id: string;
  seasons: Record<string, Partial<Record<Variant, Metrics>>>;
  forecasts: string[];
  excluded_protected_period: number;
  scope: string;
  use: string;
};

export type MapsStatus = {
  model_id: string;
  cases: number;
  forecasts: string[];
  excluded_protected_period: number;
  metrics: Record<
    string,
    { title: string; min_cases: number; available: boolean }
  >;
  variants: Variant[];
  cases_by_variant?: Partial<Record<Variant, number>>;
  default_variant?: Variant;
};

export type BulletinStatus = {
  forecast_id: string;
  title?: string;
  generator: {
    status: string;
    missing_dependency?: string;
    how_to_supply?: string;
    template?: string;
    review?: string;
    layout_validation?: string;
  };
  export?: string;
  sections?: {
    key: string;
    title: string;
    text: string[];
    leads?: string[];
    map?: string;
    missing_dependency?: string;
  }[];
  inputs: {
    interpretation: string;
    countries: string;
    maps: Record<string, string>;
  };
};

export type Health = {
  status: string;
  mode: string;
  /** The deployed source revision (absent on releases before it was reported). */
  version?: string;
  components: Record<string, string>;
};

export type Capabilities = {
  pressure_steps_configured: boolean;
  hybrid: { status: "available" | "in_progress"; reason: string | null };
  input_sources: string[];
  map_layers: string[];
  verification_maps: Record<string, string>;
  countries: string[];
  protected_test_period: string;
};

export type EcmwfInput = {
  id: string;
  initialization: string;
  file: string;
  mirror: string;
  members: number;
  steps_hours: number[];
  grib_sha256: string;
  grib_bytes: number;
  bytes: number;
  fetched_at: string;
  fetched_by: string;
};

export type ChirpsWindow = {
  id: string;
  valid_start: string;
  valid_end: string;
  products: string[];
  file: string;
  fetched_at: string;
  fetched_by: string;
  days: {
    day: string;
    product: string;
    url: string;
    sha256: string;
    missing_domain_cells: number;
  }[];
};

export type DataSource = {
  id: string;
  name: string;
  role: string;
  status: "active" | "planned";
  description: string;
  provider: string;
  url: string;
  fetched?: number;
  latest?: (EcmwfInput | ChirpsWindow) | null;
};

export type OperationAction =
  | "fetch_ecmwf"
  | "run_forecast"
  | "verify_due"
  | "verify_forecast"
  | "update_chirps"
  | "cycle";

export type Operation = {
  id: string;
  action: OperationAction;
  title: string;
  status: "queued" | "running" | "complete" | "failed" | "interrupted";
  initialization: string | null;
  forecast_id: string | null;
  created_at: string;
  created_by: string;
  started_at?: string;
  finished_at?: string;
  messages: { time: string; text: string }[];
  result: Record<string, unknown> | null;
  error: string | null;
};

/** Figures of a CHIRPS dekad over an area (cos-latitude weighted means). */
export type DekadFigures = {
  mean_mm: number;
  max_mm: number;
  /** Share of the area with less than 1 mm. */
  dry_fraction: number;
  normal_mm?: number;
  percent_of_normal?: number | null;
};

/** A CHIRPS preliminary dekad downloaded for rainfall monitoring. */
export type Dekad = {
  dekad: string;
  year: number;
  month: number;
  number: number;
  start: string;
  end: string;
  product: string;
  region: DekadFigures;
  countries: (DekadFigures & { country: string })[];
  percent_of_normal: {
    status: "available" | "in_progress";
    reason: string | null;
  };
  fetched_at: string;
  fetched_by: string;
  overlays?: { total: string; percent?: string };
  overlay_bounds?: [number, number, number, number];
};
