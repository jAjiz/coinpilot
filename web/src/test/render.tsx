import { render } from "@testing-library/react";
import type { HttpHandler } from "msw";
import { RouterProvider, createMemoryRouter } from "react-router";
import { Providers, createQueryClient } from "@/providers";
import { routes } from "@/routes";
import { server } from "./server";

export function renderAt(path: string, handlers: HttpHandler[] = []) {
  server.use(...handlers);
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <Providers client={createQueryClient()}>
      <RouterProvider router={router} />
    </Providers>,
  );
  return router;
}
