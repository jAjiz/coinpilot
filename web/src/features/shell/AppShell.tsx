import { NavLink, Outlet } from "react-router";
import { cn } from "cn";
import { OfflineNotice } from "./OfflineNotice";

const TABS = [
  { to: "/", label: "Home" },
  { to: "/history", label: "History" },
  { to: "/settings", label: "Settings" },
];

export function AppShell() {
  return (
    <div className="mx-auto flex min-h-dvh max-w-md flex-col">
      <OfflineNotice />
      <main className="flex-1 p-6">
        <Outlet />
      </main>
      <nav
        aria-label="Main"
        className="sticky bottom-0 flex border-t bg-background"
      >
        {TABS.map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            end={tab.to === "/"}
            className={({ isActive }) =>
              cn(
                "flex-1 py-3 text-center text-sm",
                isActive
                  ? "font-semibold text-primary"
                  : "text-muted-foreground",
              )
            }
          >
            {tab.label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
