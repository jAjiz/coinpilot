import { Navigate, type RouteObject } from "react-router";
import { LoginPage } from "@/features/auth/LoginPage";
import {
  OnboardingGate,
  RequireOnboarded,
  RequireSession,
} from "@/features/auth/guards";
import { DashboardPage } from "@/features/dashboard/DashboardPage";
import { HistoryPage } from "@/features/history/HistoryPage";
import { OnboardingPage } from "@/features/onboarding/OnboardingPage";
import { ProposalPage } from "@/features/proposal/ProposalPage";
import { SettingsPage } from "@/features/settings/SettingsPage";
import { AppShell } from "@/features/shell/AppShell";

export const routes: RouteObject[] = [
  { path: "/login", element: <LoginPage /> },
  {
    element: <RequireSession />,
    children: [
      {
        element: <OnboardingGate />,
        children: [
          { path: "/onboarding", element: <OnboardingPage /> },
          { path: "/onboarding/:step", element: <OnboardingPage /> },
        ],
      },
      {
        element: <RequireOnboarded />,
        children: [
          {
            element: <AppShell />,
            children: [
              { path: "/", element: <DashboardPage /> },
              { path: "/proposal", element: <ProposalPage /> },
              { path: "/history", element: <HistoryPage /> },
              { path: "/settings", element: <SettingsPage /> },
            ],
          },
        ],
      },
    ],
  },
  { path: "*", element: <Navigate to="/" replace /> },
];
