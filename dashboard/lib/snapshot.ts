import fs from "node:fs";
import path from "node:path";
import bundled from "@/data/pipeline.json";
import type { Snapshot } from "./types";

/**
 * The dashboard reads a snapshot produced by scripts/pipeline_status.py.
 *
 * Vercel runs serverless and has no access to the machine that owns the
 * output/ folder, so the snapshot is committed to the repo and redeployed
 * whenever the pipeline syncs it. Importing the JSON guarantees it is bundled
 * into the deployment; the filesystem read is only there so `npm run sync`
 * shows up during local development without restarting the dev server.
 */
export function readSnapshot(): Snapshot {
  try {
    const file = path.join(process.cwd(), "data", "pipeline.json");
    const raw = fs.readFileSync(file, "utf-8");
    return JSON.parse(raw) as Snapshot;
  } catch {
    return bundled as unknown as Snapshot;
  }
}
