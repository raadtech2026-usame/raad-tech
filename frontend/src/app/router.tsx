import { createBrowserRouter } from "react-router-dom";
import { RouteGuard } from "./RouteGuard";
import { LoginPage } from "./LoginPage";
import { DashboardLayout } from "./DashboardLayout";
import { DashboardHomePage } from "./DashboardHomePage";

export const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  {
    path: "/",
    element: (
      <RouteGuard>
        <DashboardLayout />
      </RouteGuard>
    ),
    children: [{ index: true, element: <DashboardHomePage /> }],
  },
]);
