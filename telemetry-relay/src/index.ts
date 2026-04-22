/**
 * Bicameral telemetry relay — Cloudflare Worker
 *
 * Accepts POST /event from bicameral-mcp clients.
 * Validates schema, rate-limits per device_id, then forwards to PostHog.
 * The PostHog API key never leaves this Worker — it's a Cloudflare secret.
 *
 * Privacy guarantees enforced here (second layer after the client):
 *   - Rejects events where `diagnostic` contains string values
 *   - Rejects events missing required numeric/boolean fields
 *   - Strips any fields not in the allowed list before forwarding
 */

export interface Env {
  POSTHOG_API_KEY: string;         // wrangler secret put POSTHOG_API_KEY
  RATE_LIMIT_KV: KVNamespace;      // wrangler kv:namespace create RATE_LIMIT_KV
  POSTHOG_HOST?: string;           // optional override, defaults to app.posthog.com
}

const ALLOWED_TOOLS = new Set([
  "bicameral.ingest",
  "bicameral.preflight",
  "bicameral.link_commit",
  "bicameral.history",
  "bicameral.dashboard",
  "bicameral.search",
  "bicameral.brief",
  "bicameral.reset",
  "bicameral.update",
  "bicameral.judge_gaps",
  "bicameral.resolve_compliance",
  "bicameral.ratify",
  "bicameral.drift",
  "bicameral.usage_summary",
  "validate_symbols",
  "search_code",
  "get_neighbors",
  "extract_symbols",
]);

// Max events per device_id per minute. Generous enough for heavy legit usage,
// tight enough to stop replay attacks.
const MAX_EVENTS_PER_MINUTE = 60;

interface EventPayload {
  distinct_id: string;
  tool: string;
  version: string;
  duration_ms: number;
  errored: boolean;
  diagnostic?: Record<string, number | boolean>;
}

function validatePayload(body: unknown): EventPayload | null {
  if (!body || typeof body !== "object") return null;
  const b = body as Record<string, unknown>;

  if (
    typeof b.distinct_id !== "string" || b.distinct_id.length < 10 ||
    typeof b.tool !== "string" ||
    typeof b.version !== "string" ||
    typeof b.duration_ms !== "number" ||
    typeof b.errored !== "boolean"
  ) {
    return null;
  }

  // Only forward known tool names — rejects garbage injections.
  if (!ALLOWED_TOOLS.has(b.tool as string)) return null;

  // Strip string values from diagnostic (privacy second line of defence).
  const diagnostic: Record<string, number | boolean> = {};
  if (b.diagnostic && typeof b.diagnostic === "object") {
    for (const [k, v] of Object.entries(b.diagnostic as object)) {
      if (typeof v === "number" || typeof v === "boolean") {
        diagnostic[k] = v;
      }
    }
  }

  return {
    distinct_id: b.distinct_id as string,
    tool: b.tool as string,
    version: b.version as string,
    duration_ms: b.duration_ms as number,
    errored: b.errored as boolean,
    ...(Object.keys(diagnostic).length > 0 ? { diagnostic } : {}),
  };
}

async function checkRateLimit(kv: KVNamespace, deviceId: string): Promise<boolean> {
  const key = `rl:${deviceId}`;
  const window = Math.floor(Date.now() / 60_000); // current minute bucket

  type RLEntry = { count: number; window: number };
  const entry = await kv.get<RLEntry>(key, { type: "json" });

  if (entry && entry.window === window) {
    if (entry.count >= MAX_EVENTS_PER_MINUTE) return false;
    await kv.put(key, JSON.stringify({ count: entry.count + 1, window }), {
      expirationTtl: 120,
    });
  } else {
    await kv.put(key, JSON.stringify({ count: 1, window }), {
      expirationTtl: 120,
    });
  }
  return true;
}

async function forwardToPostHog(
  env: Env,
  event: EventPayload,
): Promise<void> {
  const host = env.POSTHOG_HOST ?? "https://app.posthog.com";
  const body = JSON.stringify({
    api_key: env.POSTHOG_API_KEY,
    batch: [
      {
        distinct_id: event.distinct_id,
        event: "tool_used",
        timestamp: new Date().toISOString(),
        properties: {
          tool: event.tool,
          version: event.version,
          duration_ms: event.duration_ms,
          errored: event.errored,
          ...(event.diagnostic ? { diagnostic: event.diagnostic } : {}),
        },
      },
    ],
  });

  await fetch(`${host}/batch/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  });
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    if (request.method !== "POST") {
      return new Response("Method Not Allowed", { status: 405 });
    }

    const url = new URL(request.url);
    if (url.pathname !== "/event") {
      return new Response("Not Found", { status: 404 });
    }

    let body: unknown;
    try {
      body = await request.json();
    } catch {
      return new Response("Bad Request: invalid JSON", { status: 400 });
    }

    const event = validatePayload(body);
    if (!event) {
      return new Response("Bad Request: schema validation failed", { status: 400 });
    }

    const allowed = await checkRateLimit(env.RATE_LIMIT_KV, event.distinct_id);
    if (!allowed) {
      return new Response("Too Many Requests", { status: 429 });
    }

    // Forward to PostHog; don't let PostHog errors surface to the client.
    try {
      await forwardToPostHog(env, event);
    } catch {
      // Swallow — the client doesn't need to know.
    }

    return new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  },
};
