import { NextRequest, NextResponse } from "next/server";
import {
  getRuns,
  pushRun,
  storeConfigured,
  tokenValid,
  type RunEvent,
} from "@/lib/store";

export const dynamic = "force-dynamic";

const noStore = { "Cache-Control": "no-store" };

const STAGES = ["download", "edit", "upload", "pipeline"] as const;
const STATES = ["running", "success", "failed", "skipped"] as const;

export async function GET() {
  if (!storeConfigured()) {
    return NextResponse.json({ runs: [], storeConfigured: false }, { headers: noStore });
  }
  try {
    return NextResponse.json(
      { runs: await getRuns(), storeConfigured: true },
      { headers: noStore },
    );
  } catch (error) {
    return NextResponse.json(
      {
        error: "Could not read runs",
        detail: error instanceof Error ? error.message : String(error),
      },
      { status: 500, headers: noStore },
    );
  }
}

/** Each scheduled job reports here when it starts, succeeds, or fails. */
export async function POST(request: NextRequest) {
  const token =
    request.headers.get("x-ingest-token") ??
    request.headers.get("authorization")?.replace(/^Bearer\s+/i, "") ??
    null;

  if (!tokenValid(token)) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401, headers: noStore });
  }
  if (!storeConfigured()) {
    return NextResponse.json(
      { error: "No KV store configured." },
      { status: 503, headers: noStore },
    );
  }

  let body: Record<string, unknown>;
  try {
    body = (await request.json()) as Record<string, unknown>;
  } catch {
    return NextResponse.json({ error: "Body must be JSON" }, { status: 400, headers: noStore });
  }

  const stage = String(body.stage ?? "");
  const status = String(body.status ?? "");
  if (!STAGES.includes(stage as (typeof STAGES)[number])) {
    return NextResponse.json(
      { error: `stage must be one of ${STAGES.join(", ")}` },
      { status: 400, headers: noStore },
    );
  }
  if (!STATES.includes(status as (typeof STATES)[number])) {
    return NextResponse.json(
      { error: `status must be one of ${STATES.join(", ")}` },
      { status: 400, headers: noStore },
    );
  }

  const startedAt = String(body.startedAt ?? new Date().toISOString());
  const finishedAt = body.finishedAt ? String(body.finishedAt) : null;

  const event: RunEvent = {
    id: String(body.id ?? `${stage}-${startedAt}`),
    stage: stage as RunEvent["stage"],
    status: status as RunEvent["status"],
    startedAt,
    finishedAt,
    durationMs:
      typeof body.durationMs === "number"
        ? body.durationMs
        : finishedAt
          ? new Date(finishedAt).getTime() - new Date(startedAt).getTime()
          : null,
    exitCode: typeof body.exitCode === "number" ? body.exitCode : null,
    message: body.message ? String(body.message).slice(0, 2000) : null,
    host: body.host ? String(body.host).slice(0, 120) : null,
    videoId: body.videoId ? String(body.videoId).slice(0, 40) : null,
    videoTitle: body.videoTitle ? String(body.videoTitle).slice(0, 300) : null,
    receivedAt: new Date().toISOString(),
  };

  try {
    await pushRun(event);
    return NextResponse.json({ ok: true, id: event.id }, { headers: noStore });
  } catch (error) {
    return NextResponse.json(
      {
        error: "Could not store event",
        detail: error instanceof Error ? error.message : String(error),
      },
      { status: 500, headers: noStore },
    );
  }
}
