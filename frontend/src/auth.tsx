// Guard для защищённых роутов. Функции входа/выхода — в auth-api.ts.
import { Navigate, useLocation } from "react-router-dom";

import { isAuthed } from "./auth-api";

/** Обёртка маршрутов: при отсутствии токена редиректит на /login. */
export function RequireAuth({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  if (!isAuthed()) return <Navigate to="/login" state={{ from: location }} replace />;
  return <>{children}</>;
}
