import type { Selection } from "@/types";
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
  selection?: Selection;
  grounding: string;
};
export type Bulletin = {
  id: string;
  /** "icpac-weekly": the ICPAC weekly bulletin of an operational forecast. */
  kind?: string;
  forecast_id?: string;
  title: string;
  status: string;
  selection: Selection;
  created_at: string;
  text: string;
  provider: string;
  fallback: string | null;
  facts_checksum: string;
  sources: Source[];
  parent_id: string | null;
  consistency: { status: string; errors: string[] };
  facts: {
    period: string;
    mean_rainfall_mm: number | null;
    metrics: Record<string, number | null>;
    provenance: Record<string, unknown>;
  };
  reviews: {
    action: string;
    actor: string;
    comment: string;
    timestamp: string;
  }[];
};
export type Job = {
  id: string;
  cycle: string;
  stage: string;
  executor: string;
  status: string;
  log: string;
  group_id: string;
  poll_error?: string;
  exit_code: number | null;
  start_time: string | null;
  end_time: string | null;
};
