import { http, HttpResponse, type HttpHandler, type JsonBodyType } from "msw";
import type { components } from "@/api/schema";
import type { Config, Portfolio, Proposal } from "@/api/queries";
import { compare, sum } from "@/lib/decimal";

type HoldingOut = components["schemas"]["HoldingOut"];
type ConfigPatch = components["schemas"]["ConfigPatch"];
type InvestOut = components["schemas"]["InvestOut"];
type RebalanceOut = components["schemas"]["RebalanceOut"];
type EvaluationOut = components["schemas"]["EvaluationOut"];
type OrderOut = components["schemas"]["OrderOut"];
type LegOut = components["schemas"]["LegOut"];

export type FakeState = {
  config: Config | null; // null: no settings yet (GET -> 404)
  registered: boolean;
  signedIn: boolean; // POST /api/auth/logout ends it: /api/auth/me then answers 401
  assets: { asset: string; pair: string; target_pct: string }[];
  portfolio: { cash: string; holdings: HoldingOut[] }; // what a refresh returns
  untradable: string[]; // PUT -> 422 "kraken has no tradable {X}/{fiat} pair"
  aliases: Record<string, string>; // PUT stores an alias under its short name, as Kraken
  keyReply: { status: number; body: unknown }; // POST /api/credentials
  snapshot: Portfolio | null; // GET /api/portfolio; null -> 404
  proposal: Proposal | null; // GET /api/proposal; null -> 404
  investPreview: InvestOut; // POST /api/invest?preview=true
  investResult: InvestOut; // POST /api/invest
  rebalanceResult: RebalanceOut; // POST /api/rebalance; its proposal becomes live
  // POST /api/proposal/approve; unset: DONE, every order of the live proposal FILLED
  approveResult?: RebalanceOut;
  sessions: EvaluationOut[]; // GET /api/sessions never lists NOTHING_TO_DO
  orders: OrderOut[]; // GET /api/orders
  nextInvestAt: string;
  nextRebalanceAt: string;
};

export type FakeRequest = { method: string; path: string; body: unknown };

const ME = { id: "u1", email: "a@b.c", provider: "google", status: "active" };

const DEFAULTS: FakeState = {
  config: null,
  registered: false,
  signedIn: true,
  assets: [],
  portfolio: { cash: "0", holdings: [] },
  untradable: [],
  aliases: {},
  keyReply: {
    status: 201,
    body: {
      validated_at: "2026-10-20T09:00:00Z",
      permissions: [
        "query-funds",
        "query-open-trades",
        "query-closed-trades",
        "modify-trades",
      ],
      ip_allowlist: ["203.0.113.7"],
      unnecessary: [],
    },
  },
  snapshot: null,
  proposal: null,
  investPreview: {
    status: "NOTHING_TO_DO",
    preview: true,
    legs: [],
    messages: ["there is no free cash to invest"],
  },
  investResult: {
    status: "NOTHING_TO_DO",
    preview: false,
    legs: [],
    messages: ["there is no free cash to invest"],
  },
  rebalanceResult: {
    status: "NOTHING_TO_DO",
    legs: [],
    proposal: null,
    messages: ["the drift is below the threshold"],
  },
  sessions: [],
  orders: [],
  nextInvestAt: "2026-10-26T11:20:00Z",
  nextRebalanceAt: "2026-11-01T11:20:00Z",
};

const DEFAULT_CONFIG = {
  invest_cash_enabled: false,
  cash_rebalance_enabled: false,
  auto_rebalance_enabled: false,
  paused: false,
  min_drift_pct: "0",
  min_order_fiat: "0",
  invest_cadence_mode: "MIN",
  invest_interval_days: null,
  invest_interval_months: null,
  invest_cadence_anchor: null,
  rebalance_cadence_mode: "MIN",
  rebalance_interval_days: null,
  rebalance_interval_months: null,
  rebalance_cadence_anchor: null,
} as const;

// The 409 of a version that is not the live one, with the live proposal.
function stale(proposal: Proposal) {
  return HttpResponse.json(
    {
      detail: "that is not the live version; read the proposal again",
      proposal,
    },
    { status: 409 },
  );
}

// Every order of the proposal (a leg without a note), filled as asked.
function filled(proposal: Proposal): RebalanceOut {
  const legs = proposal.legs
    .filter((leg) => leg.note === null)
    .map((leg): LegOut => ({
      asset: leg.asset,
      pair: leg.pair,
      side: leg.side,
      amount_fiat: leg.amount_fiat,
      minimum_fiat: leg.minimum_fiat,
      status: "FILLED",
      cl_ord_id: null,
      txid: null,
      cost: null,
      executed_volume: null,
      executed_price: null,
      fee: null,
      error: null,
      note: null,
      volume: null,
    }));
  return { status: "DONE", legs, proposal: null, messages: [] };
}

// The settings each next run is computed from, as core/schedule.py lists them.
// `paused` too: lifting a pause waits for the next slot instead of running
// what was missed.
const SOURCES = {
  invest: [
    "paused",
    "invest_cash_enabled",
    "invest_cadence_mode",
    "invest_interval_days",
    "invest_interval_months",
    "invest_cadence_anchor",
  ],
  rebalance: [
    "paused",
    "rebalance_cadence_mode",
    "rebalance_interval_days",
    "rebalance_interval_months",
    "rebalance_cadence_anchor",
  ],
} as const;

// The first run after now. An interval steps from its anchor; a MIN cadence
// keeps the time of day it had, a day at a time. A run still ahead stays.
function nextRun(
  config: Config,
  prefix: "invest" | "rebalance",
  current: string,
): string {
  const anchor = config[`${prefix}_cadence_anchor`];
  const interval =
    config[`${prefix}_cadence_mode`] === "INTERVAL" && anchor !== null;
  const days = interval ? (config[`${prefix}_interval_days`] ?? 0) : 1;
  const months = interval ? (config[`${prefix}_interval_months`] ?? 0) : 0;
  if (days === 0 && months === 0) return current;
  if (!interval && new Date(current).getTime() > Date.now()) return current;
  const at = new Date(interval ? anchor : current);
  while (at.getTime() <= Date.now()) {
    at.setUTCDate(at.getUTCDate() + days);
    at.setUTCMonth(at.getUTCMonth() + months);
  }
  return at.toISOString();
}

function detail(status: number, message: string) {
  return HttpResponse.json({ detail: message }, { status });
}

// The platform in memory, for component tests. A test that needs an error
// passes its own handler before `handlers` in renderAt's list.
export function fakePlatform(initial: Partial<FakeState> = {}): {
  handlers: HttpHandler[];
  state: FakeState;
  // every non-GET request, in order, the portfolio refresh POST included
  requests: FakeRequest[];
} {
  const state: FakeState = { ...DEFAULTS, ...initial };
  const requests: FakeRequest[] = [];

  async function record(request: Request): Promise<unknown> {
    const text = await request.text();
    const body: unknown = text === "" ? null : JSON.parse(text);
    const url = new URL(request.url);
    requests.push({
      method: request.method,
      path: url.pathname + url.search,
      body,
    });
    return body;
  }

  // 100 minus the stored targets, as the platform computes it.
  function cashTarget(): string {
    return sum(["100", ...state.assets.map((a) => `-${a.target_pct}`)]);
  }

  function withSchedule(config: Config): Config {
    // A test may seed a partial configuration; the platform always sends all.
    return {
      ...DEFAULT_CONFIG,
      ...config,
      next_invest_at: config.invest_cash_enabled ? state.nextInvestAt : null,
      next_rebalance_at: state.nextRebalanceAt,
    };
  }

  const handlers = [
    http.get("/api/auth/me", () =>
      state.signedIn ? HttpResponse.json(ME) : detail(401, "not signed in"),
    ),
    http.post("/api/auth/refresh", () => detail(401, "refresh refused")),
    http.post("/api/auth/logout", async ({ request }) => {
      await record(request);
      state.signedIn = false;
      return new HttpResponse(null, { status: 204 });
    }),

    http.get("/api/config", () =>
      state.config === null
        ? detail(404, "no settings")
        : HttpResponse.json(withSchedule(state.config)),
    ),
    http.patch("/api/config", async ({ request }) => {
      const patch = (await record(request)) as ConfigPatch;
      const { onboarded, ...fields } = patch;
      if (state.config === null && !patch.fiat) {
        return detail(409, "settings need a fiat first");
      }
      if (
        state.config !== null &&
        patch.fiat &&
        patch.fiat !== state.config.fiat
      ) {
        return detail(422, "the fiat cannot be changed");
      }
      const base: Config = state.config ?? {
        ...DEFAULT_CONFIG,
        fiat: patch.fiat!,
        next_invest_at: null,
        next_rebalance_at: null,
        onboarded_at: null,
      };
      // Like the real route (exclude_unset): a field sent as null is cleared.
      const sent = Object.fromEntries(
        Object.entries(fields).filter(([, value]) => value !== undefined),
      );
      state.config = { ...base, ...sent } as Config;
      // A change to what a next run is computed from reschedules it, as the
      // platform does.
      const touches = (prefix: "invest" | "rebalance") =>
        Object.keys(sent).some((k) =>
          (SOURCES[prefix] as readonly string[]).includes(k),
        );
      if (touches("invest")) {
        state.nextInvestAt = nextRun(
          state.config,
          "invest",
          state.nextInvestAt,
        );
      }
      if (touches("rebalance")) {
        state.nextRebalanceAt = nextRun(
          state.config,
          "rebalance",
          state.nextRebalanceAt,
        );
      }
      if (onboarded) state.config.onboarded_at = "2026-10-20T10:00:00Z";
      return HttpResponse.json(withSchedule(state.config));
    }),

    http.get("/api/credentials/status", () =>
      HttpResponse.json(
        state.registered
          ? {
              registered: true,
              validated_at: "2026-10-20T09:00:00Z",
              key_version: 1,
            }
          : { registered: false },
      ),
    ),
    http.post("/api/credentials", async ({ request }) => {
      await record(request);
      const { status, body } = state.keyReply;
      if (status >= 200 && status < 300) state.registered = true;
      return HttpResponse.json(body as JsonBodyType, { status });
    }),

    http.delete("/api/credentials", async ({ request }) => {
      await record(request);
      if (!state.registered) return detail(404, "no key is registered");
      state.registered = false;
      return new HttpResponse(null, { status: 204 });
    }),

    http.get("/api/assets", () =>
      HttpResponse.json({
        assets: state.assets,
        cash_target_pct: cashTarget(),
      }),
    ),
    http.put("/api/assets/:asset", async ({ request, params }) => {
      const body = (await record(request)) as { target_pct: string | number };
      const asset = state.aliases[String(params.asset)] ?? String(params.asset);
      const target = String(body.target_pct);
      if (state.config === null) {
        return detail(409, "choose a fiat with PATCH /api/config first");
      }
      const fiat = state.config.fiat;
      if (state.untradable.includes(asset)) {
        return detail(422, `kraken has no tradable ${asset}/${fiat} pair`);
      }
      const others = state.assets.filter((a) => a.asset !== asset);
      const total = sum([...others.map((a) => a.target_pct), target]);
      if (compare(total, "100") === 1) {
        return detail(
          422,
          `the weights would sum to ${total}; the limit is 100`,
        );
      }
      const stored = { asset, pair: `${asset}/${fiat}`, target_pct: target };
      state.assets = [...others, stored].sort((a, b) =>
        a.asset < b.asset ? -1 : 1,
      );
      return HttpResponse.json(stored);
    }),
    http.delete("/api/assets/:asset", async ({ request, params }) => {
      await record(request);
      if (!state.assets.some((a) => a.asset === params.asset)) {
        return detail(404, "that asset has no weight");
      }
      state.assets = state.assets.filter((a) => a.asset !== params.asset);
      return new HttpResponse(null, { status: 204 });
    }),

    http.get("/api/portfolio", () =>
      state.snapshot === null
        ? detail(
            404,
            "no snapshot yet; POST /api/portfolio/refresh to take one",
          )
        : HttpResponse.json(state.snapshot),
    ),
    http.get("/api/proposal", () =>
      state.proposal === null
        ? detail(404, "there is no live proposal")
        : HttpResponse.json(state.proposal),
    ),
    http.delete("/api/proposal", async ({ request }) => {
      await record(request);
      const query = new URL(request.url).searchParams.get("version");
      // The platform requires the version: FastAPI's validation error.
      if (query === null) {
        return HttpResponse.json(
          {
            detail: [
              {
                type: "missing",
                loc: ["query", "version"],
                msg: "Field required",
              },
            ],
          },
          { status: 422 },
        );
      }
      const version = Number(query);
      if (state.proposal === null) {
        return detail(404, "there is no live proposal");
      }
      if (version !== state.proposal.version) {
        return stale(state.proposal);
      }
      state.proposal = null;
      return new HttpResponse(null, { status: 204 });
    }),

    http.post("/api/proposal/approve", async ({ request }) => {
      const body = (await record(request)) as { version: number };
      if (state.proposal === null) {
        return detail(404, "there is no live proposal");
      }
      if (body.version !== state.proposal.version) {
        return stale(state.proposal);
      }
      const result = state.approveResult ?? filled(state.proposal);
      state.proposal = null;
      return HttpResponse.json(result);
    }),

    // Newest first by (started_at, id), as the platform orders them.
    http.get("/api/sessions", ({ request }) => {
      const query = new URL(request.url).searchParams;
      const limit = Number(query.get("limit") ?? 50);
      const before = query.get("before");
      const listed = state.sessions
        .filter((s) => s.status !== "NOTHING_TO_DO")
        .sort((a, b) =>
          a.started_at === b.started_at
            ? b.id.localeCompare(a.id)
            : b.started_at.localeCompare(a.started_at),
        );
      let from = 0;
      if (before !== null) {
        const at = listed.findIndex((s) => s.id === before);
        if (at === -1) return detail(404, "that session no longer exists");
        from = at + 1;
      }
      return HttpResponse.json(listed.slice(from, from + limit));
    }),
    // A session's orders, oldest first; without a session, newest first.
    http.get("/api/orders", ({ request }) => {
      const query = new URL(request.url).searchParams;
      const limit = Number(query.get("limit") ?? 50);
      const session = query.get("session");
      const listed = state.orders
        .filter((o) => session === null || o.session_id === session)
        .sort((a, b) =>
          session === null
            ? b.created_at.localeCompare(a.created_at)
            : a.created_at.localeCompare(b.created_at),
        );
      return HttpResponse.json(listed.slice(0, limit));
    }),

    http.post("/api/invest", async ({ request }) => {
      await record(request);
      const preview = new URL(request.url).searchParams.get("preview");
      return HttpResponse.json(
        preview === "true" ? state.investPreview : state.investResult,
      );
    }),

    http.post("/api/rebalance", async ({ request }) => {
      await record(request);
      state.proposal = state.rebalanceResult.proposal;
      return HttpResponse.json(state.rebalanceResult);
    }),

    http.post("/api/portfolio/refresh", async ({ request }) => {
      await record(request);
      if (state.config === null) return detail(409, "no settings yet");
      const targetOf = new Map(
        state.assets.map((a) => [a.asset, a.target_pct]),
      );
      const held = state.portfolio.holdings.map((h) => ({
        ...h,
        managed: targetOf.has(h.asset),
        target_pct: targetOf.get(h.asset) ?? null,
      }));
      const managedOnly = state.assets
        .filter((a) => !held.some((h) => h.asset === a.asset))
        .map((a): HoldingOut => ({
          asset: a.asset,
          amount: "0",
          price: null,
          value: "0",
          managed: true,
          locked: false,
          target_pct: a.target_pct,
          weight_pct: "0",
        }));
      const holdings = [...held, ...managedOnly];
      const total = sum([
        state.portfolio.cash,
        ...holdings.map((h) => h.value ?? "0"),
      ]);
      const snapshot: Portfolio = {
        as_of: "2026-10-20T10:00:00Z",
        fiat: state.config.fiat,
        total_value: total,
        cash: state.portfolio.cash,
        cash_target_pct: cashTarget(),
        cash_weight_pct: null,
        holdings,
      };
      state.snapshot = snapshot;
      return HttpResponse.json(snapshot);
    }),
  ];

  return { handlers, state, requests };
}
