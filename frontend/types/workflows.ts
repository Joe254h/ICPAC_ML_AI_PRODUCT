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
export type ChatMessage = {
  role: "user" | "assistant";
  text: string;
  created_at?: string;
  provider?: string;
  fallback?: string | null;
  sources?: Source[];
  tool_trace?: ToolTrace[];
  context?: ChatContext;
  links?: { label: string; url: string }[];
  images?: { url: string; alt: string }[];
  /** forecast: built from the service's data; general: background knowledge. */
  kind?: "forecast" | "general";
  /** What the answer is based on, in words. */
  evidence?: string[];
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
