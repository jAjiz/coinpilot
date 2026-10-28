import { render } from "@testing-library/react";
import type { HttpHandler } from "msw";
import { RouterProvider, createMemoryRouter } from "react-router";
import { claimOpenRead } from "@/api/queries";
import { Providers, createQueryClient } from "@/providers";
import { routes } from "@/routes";
import { server } from "./server";

export function renderAt(
  path: string,
  handlers: HttpHandler[] = [],
  client = createQueryClient(),
  { readOnOpen = false }: { readOnOpen?: boolean } = {},
) {
  // Opening Home reads Kraken once per load; only the tests about that read
  // see it, the rest start from the snapshot they set.
  if (!readOnOpen) claimOpenRead(client);
  server.use(...handlers);
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <Providers client={client}>
      <RouterProvider router={router} />
    </Providers>,
  );
  return router;
}
