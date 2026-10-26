import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
import { afterAll, afterEach, beforeAll } from "vitest";
import { server } from "./server";

// A worker's first render of a page pays a cold start (module graph, jsdom,
// MSW). Measured in full parallel runs it takes 1.0-1.9 s against 0.4 s alone,
// past Testing Library's 1000 ms default. 4000 ms stays under Vitest's 5000 ms
// test timeout so a real failure still reports the query, not a bare timeout.
configure({ asyncUtilTimeout: 4000 });

beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterEach(() => {
  server.resetHandlers();
  cleanup();
});
afterAll(() => server.close());
