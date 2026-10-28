export type Source = {
  id: string;
  title: string;
  category: string;
  checksum: string;
  synthetic: boolean;
  excerpt: string;
  url: string;
};
export type ToolTrace = {
  tool: string;
  arguments: Record<string, unknown>;
  result: Record<string, unknown>;
};
/** A file attached to a question (its content stays on the server). */
export type ChatAttachment = {
  id: string;
  name: string;
  kind: "text" | "image" | "binary";
  bytes: number;
  characters?: number;
  truncated?: boolean;
  note?: string | null;
};

export type ChatMessage = {
  role: "user" | "assistant";
  text: string;
  created_at?: string;
  attachments?: ChatAttachment[];
  provider?: string;
  fallback?: string | null;
  /** Why the assistant did not answer, in words. */
  fallback_reason?: string | null;
  sources?: Source[];
  tool_trace?: ToolTrace[];
  context?: ChatContext;
  links?: { label: string; url: string }[];
  images?: { url: string; alt: string }[];
  /** forecast: built from the service's data; general: background knowledge. */
  kind?: "forecast" | "general";
  /** What the answer is based on, in words. */
  evidence?: string[];
  /** The weekly bulletin draft the answer shows (or the new version it wrote). */
  bulletin?: ChatBulletin | null;
  /** An uploaded forecast of another model compared with ICPAC's. */
  comparison?: ChatComparison | null;
};
/** Who asked for a draft's changes, and what changed. */
export type BulletinEdit = {
  by: string;
  with?: string;
  request?: string;
  summary?: string;
  /** A translated version: the language it is in. */
  language?: string;
  changed?: string[];
  at?: string;
};
/** Another model's uploaded forecast next to ICPAC's, and both against the observations. */
export type ChatComparison = {
  id: string;
  name: string;
  period: string;
  uploaded_by: string;
  status: "available" | "waiting";
  waiting_for?: string | null;
  versus: {
    main_layer: string;
    region_theirs_mm: number | null;
    region_ours_mm: number | null;
    pattern_correlation: number | null;
  } | null;
  scores: {
    label: string;
    mae_mm: number;
    rmse_mm: number;
    bias_mm: number;
    correlation: number | null;
    closest: boolean;
  }[];
  countries: {
    country: string;
    theirs_mean_mm: number | null;
    ours_mean_mm: number | null;
    observed_mean_mm?: number | null;
    closer: "theirs" | "ours" | null;
  }[];
  verdict: string;
};
export type ChatBulletin = {
  id: string;
  title: string;
  version: number;
  status: "draft" | "under_review" | "approved" | "published" | "rejected";
  edited?: BulletinEdit | null;
  sections: {
    key: string;
    title: string;
    text: string[];
    why?: string;
    note: boolean;
    changed: boolean;
  }[];
};
export type ChatContext = {
  mode: "operational" | "demonstration";
  country: string;
  variant?: "hybrid" | "mbc" | "raw";
  forecast_id?: string;
  model_id?: string;
  model_status?: string;
  valid_start?: string;
  valid_end?: string;
  synthetic?: boolean;
};
export type ChatSession = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  messages?: ChatMessage[];
  context?: ChatContext;
  /** Archived: out of the conversation list, kept until deleted. */
  archived?: boolean;
};
export type ChatAnswer = ChatMessage & {
  session_id: string;
  grounding: string;
};
export type BulletinSection = {
  key: string;
  title: string;
  text: string[];
  leads: string[];
  missing_dependency?: string;
  /** The country focus: why this country was chosen. */
  why?: string;
  /** A section the forecaster added. */
  note?: boolean;
  edited?: boolean;
};
export type Bulletin = {
  id: string;
  /** "icpac-weekly": the ICPAC weekly bulletin of an operational forecast. */
  kind?: string;
  forecast_id?: string;
  title: string;
  status: "draft" | "under_review" | "approved" | "published" | "rejected";
  created_at: string;
  created_by?: string;
  text: string;
  facts_checksum: string;
  parent_id: string | null;
  /** Version 1 is a forecast's first draft; each revision adds one. */
  version?: number;
  edited?: BulletinEdit | null;
  consistency: { status: string; errors: string[] };
  facts: {
    title: string;
    period: string;
    label: string;
    forecast_id: string;
    sections: BulletinSection[];
    provenance: Record<string, unknown>;
  };
  reviews: {
    action: string;
    actor: string;
    comment: string;
    timestamp: string;
    from?: string;
    to?: string;
  }[];
  /** Emails sent at each step, newest last. */
  emails?: EmailNotice[];
  /** The email of the decision just taken. */
  notification?: EmailNotice;
};

export type EmailNotice = {
  step?: string;
  at?: string;
  sent?: string[];
  failed?: { to: string; reason: string }[];
  skipped?: string | null;
};

export type EmailStatus = {
  configured: boolean;
  problem: string | null;
  reviewers: number;
  publishers: number;
  distribution: number;
};

export type EmailAction = {
  step: "review" | "publish";
  email: string;
  decisions: ("approve" | "reject" | "publish")[];
  reason: string | null;
  bulletin: {
    id: string;
    title: string;
    status: Bulletin["status"];
    headline: string;
    period?: string;
    reviews: Bulletin["reviews"];
  };
};
