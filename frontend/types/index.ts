export type Model = {
  id: string;
  model_id: string;
  model_name: string;
  version: string;
  status: string;
  model_type: string;
  feature_schema: string;
  artifact_path: string | null;
  training_period: string;
  validation_period: string;
  checksum: string;
  /** "week2_operational": a Week-2 model on the ICPAC 0.05° grid. */
  task?: string;
  [key: string]: unknown;
};
export type Config = {
  /** What this deployment can do (inputs, hybrid status, countries). */
  operational: import("@/types/operational").Capabilities;
  models: Model[];
  data_sources: import("@/types/operational").DataSource[];
};
