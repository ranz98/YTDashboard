import { NextRequest, NextResponse } from "next/server";
import { readSnapshot } from "@/lib/snapshot";
import {
  getRuns,
  getSnapshot,
  setSnapshot,
  storeConfigured,
  tokenValid,
} from "@/lib/store";
import type { Snapshot } from "@/lib/types";

export const dynamic = "force-dynamic";

const noStore = { "Cache-Control": "no-store" };

/** Live state pushed by the VPS wins; otherwise the snapshot committed to the
 *  repo is served, so a fresh deploy is never blank. */
export async function GET() {
  try {
    let snapshot: Snapshot | null = null;
    let live = false;

    if (storeConfigured()) {
      snapshot = await getSnapshot();
      live = snapshot !== null;
    }
    if (!snapshot) snapshot = readSnapshot();

    const runs = storeConfigured() ? await getRuns() : [];

    return NextResponse.json(
      { ...snapshot, live, storeConfigured: storeConfigured(), runs },
      { headers: noStore },
    );
  } catch (error) {
    return NextResponse.json(
      {
        error: "Could not read the pipeline snapshot.",
        detail: error instanceof Error ? error.message : String(error),
      },
      { status: 500, headers: noStore },
    );
  }
}

/** The VPS pushes a full snapshot here after each stage finishes. */
export async function POST(request: NextRequest) {
  const token =
    request.headers.get("x-ingest-token") ??
    request.headers.get("authorization")?.replace(/^Bearer\s+/i, "") ??
    null;

  if (!tokenValid(token)) {
    return NextResponse.json(
      { error: "Unauthorized" },
      { status: 401, headers: noStore },
    );
  }

  if (!storeConfigured()) {
    return NextResponse.json(
      {
        error:
          "No KV store configured. Set KV_REST_API_URL and KV_REST_API_TOKEN " +
          "(or the UPSTASH_* equivalents) in the Vercel project.",
      },
      { status: 503, headers: noStore },
    );
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      { error: "Body must be JSON" },
      { status: 400, headers: noStore },
    );
  }

  const snapshot = body as Snapshot;
  if (!snapshot || !Array.isArray(snapshot.videos) || !snapshot.summary) {
    return NextResponse.json(
      { error: "Expected a snapshot with videos[] and summary" },
      { status: 400, headers: noStore },
    );
  }

  try {
    await setSnapshot(snapshot);
    return NextResponse.json(
      { ok: true, videos: snapshot.videos.length },
      { headers: noStore },
    );
  } catch (error) {
    return NextResponse.json(
      {
        error: "Could not store snapshot",
        detail: error instanceof Error ? error.message : String(error),
      },
      { status: 500, headers: noStore },
    );
  }
}
