import type { Snapshot } from "./types";

/**
 * Storage for live pipeline state pushed from the VPS.
 *
 * Vercel is serverless, so nothing survives between requests in process
 * memory. State goes to a Redis-compatible REST store instead - Vercel KV and
 * Upstash both expose the same REST shape, so plain fetch covers both and the
 * dashboard needs no extra npm dependency.
 *
 * When no store is configured the dashboard still works: reads fall back to
 * the snapshot committed in data/pipeline.json, and writes report that they
 * were not persisted rather than failing silently.
 */

const URL_ENV = ["KV_REST_API_URL", "UPSTASH_REDIS_REST_URL"];
const TOKEN_ENV = ["KV_REST_API_TOKEN", "UPSTASH_REDIS_REST_TOKEN"];

const SNAPSHOT_KEY = "pipeline:snapshot";
const RUNS_KEY = "pipeline:runs";
const MAX_RUNS = 200;

function firstEnv(names: string[]): string | null {
  for (const name of names) {
    const value = process.env[name];
    if (value && value.trim()) return value.trim();
  }
  return null;
}

export function storeConfigured(): boolean {
  return Boolean(firstEnv(URL_ENV) && firstEnv(TOKEN_ENV));
}

async function command<T>(args: (string | number)[]): Promise<T | null> {
  const base = firstEnv(URL_ENV);
  const token = firstEnv(TOKEN_ENV);
  if (!base || !token) return null;

  const res = await fetch(base, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(args),
    cache: "no-store",
  });

  if (!res.ok) {
    throw new Error(`KV command failed: ${res.status} ${await res.text()}`);
  }
  const body = (await res.json()) as { result?: T; error?: string };
  if (body.error) throw new Error(`KV error: ${body.error}`);
  return (body.result ?? null) as T | null;
}

export async function getSnapshot(): Promise<Snapshot | null> {
  const raw = await command<string>(["GET", SNAPSHOT_KEY]);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as Snapshot;
  } catch {
    return null;
  }
}

export async function setSnapshot(snapshot: Snapshot): Promise<void> {
  await command(["SET", SNAPSHOT_KEY, JSON.stringify(snapshot)]);
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

export async function getRuns(): Promise<RunEvent[]> {
  const raw = await command<string[]>(["LRANGE", RUNS_KEY, 0, MAX_RUNS - 1]);
  if (!raw) return [];
  const runs: RunEvent[] = [];
  for (const item of raw) {
    try {
      runs.push(JSON.parse(item) as RunEvent);
    } catch {
      /* skip a corrupt entry rather than losing the whole list */
    }
  }
  return runs;
}

/**
 * Records a run event. A run that is already present (same id) is replaced, so
 * a job that reports "running" then "success" shows up once with its final
 * state instead of twice.
 */
export async function pushRun(event: RunEvent): Promise<void> {
  const existing = await getRuns();
  const merged = [event, ...existing.filter((r) => r.id !== event.id)].slice(
    0,
    MAX_RUNS,
  );
  await command(["DEL", RUNS_KEY]);
  if (merged.length) {
    await command(["RPUSH", RUNS_KEY, ...merged.map((r) => JSON.stringify(r))]);
  }
}

/** Constant-time-ish comparison so the token check does not leak length. */
export function tokenValid(provided: string | null): boolean {
  const expected = process.env.INGEST_TOKEN;
  if (!expected) return false;
  if (!provided) return false;
  if (provided.length !== expected.length) return false;
  let diff = 0;
  for (let i = 0; i < expected.length; i += 1) {
    diff |= provided.charCodeAt(i) ^ expected.charCodeAt(i);
  }
  return diff === 0;
}
