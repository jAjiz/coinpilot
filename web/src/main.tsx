import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider, createBrowserRouter } from "react-router";
import "./index.css";
import { Providers, createQueryClient } from "./providers";
import { routes } from "./routes";

const client = createQueryClient();
const router = createBrowserRouter(routes);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Providers client={client}>
      <RouterProvider router={router} />
    </Providers>
  </StrictMode>,
);
