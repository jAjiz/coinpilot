import { http, HttpResponse, type HttpHandler, type JsonBodyType } from "msw";
import type { components } from "@/api/schema";
import type { Config, Portfolio, Proposal } from "@/api/queries";
import { compare, sum } from "@/lib/decimal";

type HoldingOut = components["schemas"]["HoldingOut"];
type ConfigPatch = components["schemas"]["ConfigPatch"];
type InvestOut = components["schemas"]["InvestOut"];

export type FakeState = {
  config: Config | null; // null: no settings yet (GET -> 404)
  registered: boolean;
  assets: { asset: string; pair: string; target_pct: string }[];
  portfolio: { cash: string; holdings: HoldingOut[] }; // what a refresh returns
  untradable: string[]; // PUT -> 422 "kraken has no tradable {X}/{fiat} pair"
  keyReply: { status: number; body: unknown }; // POST /api/credentials
  snapshot: Portfolio | null; // GET /api/portfolio; null -> 404
  proposal: Proposal | null; // GET /api/proposal; null -> 404
  investPreview: InvestOut; // POST /api/invest?preview=true
  investResult: InvestOut; // POST /api/invest
  nextInvestAt: string;
  nextRebalanceAt: string;
};

export type FakeRequest = { method: string; path: string; body: unknown };

const ME = { id: "u1", email: "a@b.c", provider: "google", status: "active" };

const DEFAULTS: FakeState = {
  config: null,
  registered: false,
  assets: [],
  portfolio: { cash: "0", holdings: [] },
  untradable: [],
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
    return {
      ...config,
      next_invest_at: config.invest_cash_enabled ? state.nextInvestAt : null,
      next_rebalance_at: state.nextRebalanceAt,
    };
  }

  const handlers = [
    http.get("/api/auth/me", () => HttpResponse.json(ME)),

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

    http.get("/api/assets", () =>
      HttpResponse.json({
        assets: state.assets,
        cash_target_pct: cashTarget(),
      }),
    ),
    http.put("/api/assets/:asset", async ({ request, params }) => {
      const body = (await record(request)) as { target_pct: string | number };
      const asset = String(params.asset);
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
      if (state.proposal === null) {
        return detail(404, "there is no live proposal");
      }
      state.proposal = null;
      return new HttpResponse(null, { status: 204 });
    }),

    http.post("/api/invest", async ({ request }) => {
      await record(request);
      const preview = new URL(request.url).searchParams.get("preview");
      return HttpResponse.json(
        preview === "true" ? state.investPreview : state.investResult,
      );
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
