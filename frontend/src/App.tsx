import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route, Outlet } from "react-router-dom";
import { RequireAuth } from "./auth";
import { Sidebar } from "./components/Sidebar";
import { Dashboard } from "./pages/Dashboard";
import { Delivery } from "./pages/Delivery";
import { Pnl } from "./pages/Pnl";
import { Schedule } from "./pages/Schedule";
import { Login } from "./pages/Login";
import { QUERY_RETRY, STALE_TIME_MS } from "./constants";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: QUERY_RETRY, staleTime: STALE_TIME_MS } },
});

function Layout() {
  return (
    <div className="app-shell">
      <Sidebar />
      <div className="app-main">
        <Outlet />
      </div>
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route
            element={
              <RequireAuth>
                <Layout />
              </RequireAuth>
            }
          >
            <Route path="/" element={<Dashboard />} />
            <Route path="/delivery" element={<Delivery />} />
            <Route path="/pnl" element={<Pnl />} />
            <Route path="/schedule" element={<Schedule />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
