import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route, Outlet } from "react-router-dom";
import { Sidebar } from "./components/Sidebar";
import { Dashboard } from "./pages/Dashboard";
import { Suppliers } from "./pages/Suppliers";
import { SupplierCard } from "./pages/SupplierCard";
import { NewSupplier } from "./pages/NewSupplier";
import { Nomenclature } from "./pages/Nomenclature";
import { TtkCard } from "./pages/TtkCard";
import { QUERY_RETRY, STALE_TIME_MS } from "./constants";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: QUERY_RETRY, staleTime: STALE_TIME_MS } },
});

function Layout() {
  return (
    <div style={{ display: "flex", minHeight: "100vh", background: "var(--bg)" }}>
      <Sidebar />
      <div style={{ flex: 1, minWidth: 0 }}>
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
          <Route element={<Layout />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/suppliers" element={<Suppliers />} />
            <Route path="/suppliers/new" element={<NewSupplier />} />
            <Route path="/suppliers/:id" element={<SupplierCard />} />
            <Route path="/nomenclature" element={<Nomenclature />} />
            <Route path="/ttk/:id" element={<TtkCard />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
