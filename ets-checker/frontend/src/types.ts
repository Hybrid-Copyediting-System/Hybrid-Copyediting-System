export interface Locator {
  kind: "document" | "paragraph";
  paragraph_index?: number | null;
  char_start?: number | null;
  char_end?: number | null;
}

export interface CheckDetail {
  location: string;
  locator?: Locator | null;
  message: string;
  expected?: string | number | null;
  actual?: string | number | null;
  excerpt?: string | null;
}

export interface CheckResult {
  rule_id: string;
  category: string;
  name: string;
  status: "pass" | "fail";
  severity: "error" | "warning" | "info";
  details: CheckDetail[];
}

export interface ReportSummary {
  total_checks: number;
  passed: number;
  errors: number;
  warnings: number;
  info: number;
}

export interface CheckReport {
  file_name: string;
  timestamp: string;
  summary: ReportSummary;
  results: CheckResult[];
}

export type ProgressEvent =
  | { phase: "parsing"; message: string }
  | { phase: "rule"; rule_id: string; name: string; step: number; total_steps: number; message: string }
  | { phase: "links_start"; step: number; total_steps: number; message: string }
  | { phase: "links"; done: number; total: number; step: number; total_steps: number; message: string };
