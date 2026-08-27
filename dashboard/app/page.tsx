import { Dashboard } from "@/components/Dashboard";
import { readSnapshot } from "@/lib/snapshot";
import { getRuns, getSnapshot, storeConfigured } from "@/lib/store";
import type { Snapshot } from "@/lib/types";

// Rendered per request so a scheduled job's push shows on the next load,
// rather than being frozen into a static build.
export const dynamic = "force-dynamic";

export default async function Page() {
  let snapshot: Snapshot | null = null;
  let runs: Snapshot["runs"] = [];

  if (storeConfigured()) {
    try {
      snapshot = await getSnapshot();
      runs = await getRuns();
    } catch {
      // Store unreachable - fall through to the bundled snapshot rather than
      // failing the whole page.
    }
  }
  if (!snapshot) snapshot = readSnapshot();

  return <Dashboard initial={{ ...snapshot, runs }} />;
}
