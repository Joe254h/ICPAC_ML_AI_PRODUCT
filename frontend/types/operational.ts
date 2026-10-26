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
  descriptor?: {
    path: string;
    sha256: string;
    declared_by?: string;
    declared_status?: string;
  };
  notes?: string;
  /** Frozen bundle models: the policy the hybrid layer follows. */
  policy?: string;
  pressure_steps_hours?: number[];
  model_info?: Record<string, unknown>;
  bundle?: {
    bundle_id?: string;
    bundle_status?: string;
    bundle_warnings?: string[];
    trained_rows?: number;
    independent_report?: {
      rows: number;
      cases: number;
      period: string;
      rmse: number;
      mae: number;
      bias: number;
      pearson_r: number;
      anomaly_correlation?: number;
      source: string;
      selection_note: string;
    };
  };
  realtime_reviews?: Record<
    string,
    { actor: string; timestamp: string; comment: string; forecast_id: string }
  >;
  lifecycle?: Lifecycle | null;
};

export type Activation = {
  model_id: string;
  since: string;
  actor: string;
  comment: string;
  history: { model_id: string; since: string; until: string; actor?: string }[];
};

export type CurrentModel = {
  role: "production" | "candidate" | "experimental";
  model: OperationalModel;
  activation?: Activation | null;
  note?: string | null;
};

export type ProductStatus = {
  /** in_progress: waiting for an input or a review; blocked: an input failed a check;
   * not_produced: the model's policy issues MBC alone. */
  status: "available" | "in_progress" | "blocked" | "not_produced";
  reason?: string;
};

/** One check of a forecast input against the frozen model's training data. */
export type InputCheck = {
  check: string;
  status: "passed" | "note" | "failed";
  detail: string;
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

/** A model with verified forecasts, and how many. */
export type VerifiedModel = {
  model_id: string;
  model_name: string;
  cases: number;
};

export type Seasonal = {
  model_id: string;
  models?: VerifiedModel[];
  seasons: Record<string, Partial<Record<Variant, Metrics>>>;
  forecasts: string[];
  excluded_protected_period: number;
  scope: string;
  use: string;
};

export type MapsStatus = {
  model_id: string;
  models?: VerifiedModel[];
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
    /** The country focus: which member state and why it was chosen. */
    country?: string;
    why?: string;
    /** Member states' rainfall (the "countries" section). */
    rows?: {
      country: string;
      mean_mm: number;
      median_mm: number;
      max_mm: number;
    }[];
  }[];
  inputs: {
    interpretation: string;
    countries: string;
    maps: Record<string, string>;
  };
};

export type Health = {
  access_mode?: "staff" | "public";
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
  latest?: (EcmwfInput | ChirpsWindow | Dekad) | null;
  /** The last look at a monitoring source's server (TAMSAT, ARC 2.0, RFE 2.0, GPM IMERG). */
  last_check?: SourceCheck | null;
};

export type SourceCheck = {
  source: RainfallEstimate;
  checked_at: string;
  status: "new" | "held" | "failed";
  dekad?: string;
  reason?: string;
};

/** The observed-rainfall estimates held for monitoring. */
export type RainfallEstimate = "chirps" | "tamsat" | "arc2" | "rfe2" | "imerg";

/** An estimate's latest monitoring dekad and its last server check. */
export type Estimate = {
  source: RainfallEstimate;
  name: string;
  latest: Dekad | null;
  last_check: SourceCheck | null;
};

/** A verified forecast scored against a further daily reference (ARC 2.0, RFE 2.0, IMERG). */
export type ReferenceComparison = {
  forecast_id: string;
  source: "arc2" | "rfe2" | "imerg";
  name: string;
  status: "available" | "waiting" | "unavailable";
  reason?: string;
  season?: string;
  domain?: Partial<Record<Variant, Metrics>>;
  licence?: string;
  checked_at: string;
};

export type OperationAction =
  | "fetch_ecmwf"
  | "run_forecast"
  | "verify_due"
  | "verify_forecast"
  | "update_chirps"
  | "cycle"
  | "end_to_end"
  | "past_weeks"
  | "check_ecmwf";

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
  retry_at?: string | null;
  attempts?: number;
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

/** A dekad of observed rainfall (CHIRPS preliminary, TAMSAT, or summed from the daily ARC 2.0,
 * RFE 2.0 or GPM IMERG files) held for monitoring. */
export type Dekad = {
  dekad: string;
  /** Older CHIRPS records have no source. */
  source?: RainfallEstimate;
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

/** Recorded ECMWF input states for the model in use (GET /data/ecmwf/readiness). */
export type EcmwfReadiness = {
  checked_at: string;
  model: {
    model_id: string;
    model_name?: string;
    version?: string;
    family?: string;
    policy?: string | null;
    status?: string;
    role?: string | null;
    training_members?: number | null;
    pressure_steps_hours?: number[] | null;
    needs_upper_air: boolean;
    realtime_gate_from?: string | null;
  } | null;
  availability: {
    checked_at: string;
    checked_by: string;
    status: "published" | "unavailable";
    initialization: string | null;
    mirrors: string[];
    rainfall_members?: number;
    upper_air_steps_hours?: number[];
    upper_air_listed?: boolean;
    summary: string;
    error?: string;
  } | null;
  rainfall: {
    status: "available" | "incomplete" | "missing";
    initialization?: string;
    members?: number;
    steps_hours?: number[];
    week2_complete?: boolean;
    mirror?: string;
    bytes?: number;
    fetched_at?: string;
    fetched_by?: string;
    type?: string;
  };
  upper_air: {
    status:
      | "available"
      | "missing"
      | "incompatible"
      | "not_needed"
      | "not_configured";
    initialization?: string;
    members?: number;
    steps_hours?: number[];
    variables?: Record<string, number[]>;
    fetched_at?: string;
    bytes?: number;
  };
  last_run: {
    forecast_id: string;
    initialization: string;
    created_at?: string;
    primary_layer?: Variant;
    hybrid?: ProductStatus | null;
    input_checks: InputCheck[];
    input_source?: string;
    realtime_gate_required: boolean;
  } | null;
  failures: {
    action: string;
    title: string;
    error: string | null;
    finished_at?: string;
    retry_at?: string | null;
  }[];
  realtime_review: {
    actor: string;
    timestamp: string;
    comment: string;
    checks: number;
  } | null;
  compatibility: {
    status:
      | "compatible"
      | "waiting"
      | "unchecked"
      | "incompatible"
      | "awaiting_review"
      | "unknown";
    detail: string;
  };
  generation: {
    raw_mbc: { allowed: boolean; reason: string | null };
    ml: { allowed: boolean; reason: string | null };
  };
};

export type Lifecycle = {
  stage:
    | "uploaded"
    | "integrity_verified"
    | "scientifically_validated"
    | "operationally_approved"
    | "active"
    | "retired";
  states: Record<
    | "uploaded"
    | "integrity_verified"
    | "scientifically_validated"
    | "operationally_approved"
    | "active"
    | "retired",
    boolean
  >;
};

/** Scores of one model in one group of the frozen experimental verification. */
export type EvidenceScore = {
  model: string;
  label: string;
  rows?: number;
  cases?: number;
  rmse: number;
  mae: number;
  bias: number;
  pearson_r?: number | null;
  anomaly_correlation?: number | null;
  skill_vs_raw?: number;
  skill_vs_mbc?: number;
  skill_vs_climatology?: number;
};

export type RocCurve = {
  model: string;
  label: string;
  event_mmweek: number;
  auc: number;
  curve: [number, number][];
};

/** GET /verification/experimental: the frozen pre-refit independent verification. */
export type ExperimentalEvidence = {
  scope: Record<string, string | number>;
  regional: EvidenceScore[];
  foundational: {
    model: string;
    label: string;
    training_period: string;
    validation_period: string;
    validation_rmse: number;
    validation_mae: number;
    independent_period: string;
    independent_rmse: number;
    independent_mae: number;
    independent_anomaly_correlation: number;
  }[];
  annual: Record<string, EvidenceScore[]>;
  seasonal: Record<string, EvidenceScore[]>;
  monthly: Record<string, EvidenceScore[]>;
  year_season: Record<string, EvidenceScore[]>;
  countries: Record<string, EvidenceScore[]>;
  intensity: Record<string, EvidenceScore[]>;
  contingency: {
    model: string;
    label: string;
    threshold_mmweek: number;
    pod: number;
    far: number;
    false_positive_rate: number;
    csi: number;
    ets: number;
    frequency_bias: number;
    hss: number;
  }[];
  thresholds_mmweek: number[];
  deterministic_roc: RocCurve[];
  ensemble: {
    label: string;
    crps: { group: string; id: string; crps_mmweek: number }[];
    brier: {
      group: string;
      id: string;
      event_mmweek: number;
      brier_score: number;
      mean_probability: number;
    }[];
    reliability: Record<
      string,
      { probability: number; observed: number; weight: number }[]
    >;
    roc: RocCurve[];
    note: string;
  };
  bootstrap: {
    method: string;
    items: {
      primary: string;
      comparator: string;
      delta_rmse: number;
      low: number;
      high: number;
    }[];
  };
  deterministic_note: string;
  maps: { id: string; title: string }[];
  country_maps: string[];
  sudan: { cells_outside_vector: number; note: string };
};
