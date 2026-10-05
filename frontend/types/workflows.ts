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
  arguments: Selection;
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
};
export type ChatAnswer = ChatMessage & {
  session_id: string;
  selection: Selection;
  grounding: string;
};
export type Bulletin = {
  id: string;
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
