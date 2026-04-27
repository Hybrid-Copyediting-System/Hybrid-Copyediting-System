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
