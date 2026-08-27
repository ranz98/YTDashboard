export const STATUSES = [
  "scheduled",
  "processing",
  "downloaded",
  "edited",
  "uploaded",
  "successful",
  "failed",
  "cancelled",
] as const;

export type Status = (typeof STATUSES)[number];

export interface StageDownload {
  done: boolean;
  at: string | null;
  sizeBytes: number | null;
  hasFrame: boolean;
}

export interface StageEdit {
  done: boolean;
  at: string | null;
  sizeBytes: number | null;
  fileName: string | null;
}

export interface StageUpload {
  done: boolean;
  at: string | null;
  url: string | null;
  privacy: string | null;
}

export interface Video {
  id: string;
  title: string;
  originalTitle: string | null;
  rewrittenTitle: string | null;
  caption: string | null;
  status: Status;
  error: string | null;
  folder: string | null;
  batchDate: string | null;
  sourceUrl: string | null;
  channel: string | null;
  scheduledAt: string | null;
  download: StageDownload;
  edit: StageEdit;
  upload: StageUpload;
  createdAt: string | null;
  updatedAt: string | null;
  processingMs: number | null;
}

export interface Summary {
  total: number;
  byStatus: Record<Status, number>;
  downloaded: number;
  edited: number;
  uploaded: number;
  processedToday: number;
  processedThisWeek: number;
  processedThisMonth: number;
  avgProcessingMs: number | null;
}

export interface RunEvent {
  id: string;
  stage: "download" | "edit" | "upload" | "pipeline";
  status: "running" | "success" | "failed" | "skipped";
  startedAt: string;
  finishedAt: string | null;
  durationMs: number | null;
  exitCode: number | null;
  message: string | null;
  host: string | null;
  videoId: string | null;
  videoTitle: string | null;
  receivedAt: string;
}

export interface Snapshot {
  source: "live" | "demo";
  generatedAt: string;
  root: string;
  summary: Summary;
  videos: Video[];
  /** Present on API responses: live pipeline runs pushed from the VPS. */
  runs?: RunEvent[];
  /** True when the payload came from the KV store rather than the bundled file. */
  live?: boolean;
  storeConfigured?: boolean;
}

/** Pipeline order. Drives the stepper and the tab ordering. */
export const PIPELINE_ORDER: Status[] = [
  "scheduled",
  "downloaded",
  "edited",
  "uploaded",
  "successful",
];
