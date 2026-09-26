// HTTP-клиент и вызовы API. Доменные типы — в types.ts (реэкспортятся ниже,
// чтобы компоненты могли импортировать и функцию, и тип из одного места "../api").
import axios from "axios";

import { clearToken, getToken } from "./token";

import type {
  Basket,
  CheckComposition,
  CheckDistribution,
  CheckFullness,
  DaypartSummary,
  DishGroupBy,
  DishResponse,
  Employee,
  LaborSummary,
  ShiftEntry,
  HourlyBreakdown,
  HourlyResponse,
  OpsReport,
  PlanCell,
  PlanMatrix,
  KpiByChannel,
  PaymentStructure,
  PnlCostsResponse,
  PnlDayCostRow,
  PnlDayCostsResponse,
  PnlReport,
  RangeSel,
  RevenueByChannel,
  RevenueResponse,
  WeekdaySummary,
} from "./types";

export type * from "./types";

// VITE_API_URL не задан → дефолт для локальной разработки (vite :5173, backend :8000).
// В Docker-сборке прокидывается пустая строка → относительные пути, nginx проксирует /api.
const BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export const api = axios.create({ baseURL: BASE });

// На каждый запрос подставляем Bearer-токен сессии (если есть).
api.interceptors.request.use((config) => {
  const token = getToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// Истёкший/невалидный токен → 401: чистим сессию и уводим на /login
// (кроме самого запроса логина, чтобы не перебивать сообщение об ошибке формы).
api.interceptors.response.use(
  (resp) => resp,
  (error) => {
    const url: string = error.config?.url ?? "";
    if (error.response?.status === 401 && !url.includes("/api/auth/login")) {
      clearToken();
      if (window.location.pathname !== "/login") window.location.href = "/login";
    }
    return Promise.reject(error);
  },
);

/** Query-строка для API из выбора диапазона (пресет или произвольные даты). */
export const rangeQS = (r: RangeSel): string =>
  "from" in r ? `date_from=${r.from}&date_to=${r.to}` : `period=${r.period}`;

/** Стабильный ключ диапазона для queryKey React Query. */
export const rangeKey = (r: RangeSel): string =>
  "from" in r ? `${r.from}..${r.to}` : r.period;

// ---------- Выручка / часы ----------

// флаг «без доставки» (include_delivery=false) — бэкенд вычитает выручку/чеки доставки
const deliveryQS = (includeDelivery: boolean): string =>
  includeDelivery ? "" : "&include_delivery=false";

export const fetchRevenue = (
  range: RangeSel,
  includeDelivery = true,
): Promise<RevenueResponse> =>
  api
    .get<RevenueResponse>(`/api/revenue?${rangeQS(range)}${deliveryQS(includeDelivery)}`)
    .then((r) => r.data);

export const fetchHourly = (range: RangeSel, includeDelivery = true): Promise<HourlyResponse> =>
  api
    .get<HourlyResponse>(`/api/revenue/hourly?${rangeQS(range)}${deliveryQS(includeDelivery)}`)
    .then((r) => r.data);

export const fetchRevenueByChannel = (
  range: RangeSel,
  includeDelivery = true,
): Promise<RevenueByChannel> =>
  api
    .get<RevenueByChannel>(`/api/revenue/by-channel?${rangeQS(range)}${deliveryQS(includeDelivery)}`)
    .then((r) => r.data);

export const fetchKpiByChannel = (range: RangeSel): Promise<KpiByChannel> =>
  api.get<KpiByChannel>(`/api/revenue/kpi-by-channel?${rangeQS(range)}`).then((r) => r.data);

export const fetchPaymentStructure = (
  range: RangeSel,
  includeDelivery = true,
): Promise<PaymentStructure> =>
  api
    .get<PaymentStructure>(`/api/revenue/by-payment?${rangeQS(range)}${deliveryQS(includeDelivery)}`)
    .then((r) => r.data);

export const fetchRevenueByWeekday = (
  range: RangeSel,
  includeDelivery = true,
): Promise<WeekdaySummary> =>
  api
    .get<WeekdaySummary>(`/api/revenue/by-weekday?${rangeQS(range)}${deliveryQS(includeDelivery)}`)
    .then((r) => r.data);

export const fetchByDaypart = (
  range: RangeSel,
  includeDelivery = true,
): Promise<DaypartSummary> =>
  api
    .get<DaypartSummary>(`/api/revenue/by-daypart?${rangeQS(range)}${deliveryQS(includeDelivery)}`)
    .then((r) => r.data);

export const fetchOpsReport = (range: RangeSel, includeDelivery = true): Promise<OpsReport> =>
  api
    .get<OpsReport>(`/api/revenue/ops-report?${rangeQS(range)}${deliveryQS(includeDelivery)}`)
    .then((r) => r.data);

// ---------- План (цели по дейпартам × группам дня недели) ----------

export const fetchPlan = (): Promise<PlanMatrix> =>
  api.get<PlanMatrix>("/api/plan").then((r) => r.data);

export const savePlan = (cells: Record<string, PlanCell>): Promise<{ ok: boolean }> =>
  api.put<{ ok: boolean }>("/api/plan", { cells }).then((r) => r.data);

export const seedPlanFromHistory = (months = 2): Promise<{ ok: boolean; segments: number }> =>
  api.post<{ ok: boolean; segments: number }>(`/api/plan/seed-from-history?months=${months}`).then((r) => r.data);

export const fetchPnl = (range: RangeSel): Promise<PnlReport> =>
  api.get<PnlReport>(`/api/pnl?${rangeQS(range)}`).then((r) => r.data);

export const fetchPnlCosts = (year: number, month: number): Promise<PnlCostsResponse> =>
  api.get<PnlCostsResponse>(`/api/pnl/costs?year=${year}&month=${month}`).then((r) => r.data);

export const savePnlCosts = (payload: Record<string, number>): Promise<{ ok: boolean }> =>
  api.put<{ ok: boolean }>("/api/pnl/costs", payload).then((r) => r.data);

export const fetchPnlDayCosts = (dateFrom: string, dateTo: string): Promise<PnlDayCostsResponse> =>
  api.get<PnlDayCostsResponse>(`/api/pnl/day-costs?date_from=${dateFrom}&date_to=${dateTo}`).then((r) => r.data);

export const savePnlDayCosts = (days: PnlDayCostRow[]): Promise<{ ok: boolean }> =>
  api.put<{ ok: boolean }>("/api/pnl/day-costs", { days }).then((r) => r.data);

export interface PnlImportResult {
  months: number;
  imported: { year: number; month: number }[];
  skipped: { year: number; month: number }[];
}

export const importPnlSheet = (): Promise<PnlImportResult> =>
  api.post<PnlImportResult>("/api/pnl/import-sheet").then((r) => r.data);

// ─── График и ФОТ ────────────────────────────────────────────────────────────
export const fetchEmployees = (): Promise<Employee[]> =>
  api.get<Employee[]>("/api/schedule/employees").then((r) => r.data);

export const createEmployee = (p: Partial<Employee>): Promise<Employee> =>
  api.post<Employee>("/api/schedule/employees", p).then((r) => r.data);

export const updateEmployee = (id: number, p: Partial<Employee>): Promise<Employee> =>
  api.put<Employee>(`/api/schedule/employees/${id}`, p).then((r) => r.data);

export const deleteEmployee = (id: number): Promise<{ ok: boolean }> =>
  api.delete(`/api/schedule/employees/${id}`).then((r) => r.data);

export const fetchShifts = (year: number, month: number): Promise<ShiftEntry[]> =>
  api.get<ShiftEntry[]>(`/api/schedule/shifts?year=${year}&month=${month}`).then((r) => r.data);

export const toggleShift = (employee_id: number, date: string): Promise<{ on: boolean }> =>
  api.post<{ on: boolean }>("/api/schedule/shifts/toggle", { employee_id, date }).then((r) => r.data);

export const fetchLabor = (year: number, month: number): Promise<LaborSummary> =>
  api.get<LaborSummary>(`/api/schedule/labor?year=${year}&month=${month}`).then((r) => r.data);

/** Запустить синхронизацию. `days>0` — лёгкий синк за последние N дней (автосинхронизация),
 *  без аргумента — полный синк (кнопка «Синхронизировать»). */
export const triggerSync = (days?: number) =>
  api.post(`/api/sync${days ? `?days=${days}` : ""}`);

/** Время последней успешной синхронизации (ISO в UTC) либо null, если синков ещё не было. */
export const fetchLastSync = (): Promise<{ last_sync: string | null; sync_type?: string }> =>
  api.get<{ last_sync: string | null; sync_type?: string }>("/api/sync/last").then((r) => r.data);

// ---------- Продажи блюд ----------

export const fetchDishes = (
  range: RangeSel,
  groupBy: DishGroupBy = "dish",
  includeDelivery = true,
): Promise<DishResponse> =>
  api
    .get<DishResponse>(
      `/api/dishes?${rangeQS(range)}&group_by=${groupBy}${deliveryQS(includeDelivery)}`,
    )
    .then((r) => r.data);

export const fetchHourlyBreakdown = (
  range: RangeSel,
  group: DishGroupBy,
  includeDelivery = true,
): Promise<HourlyBreakdown> =>
  api
    .get<HourlyBreakdown>(
      `/api/dishes/hourly-breakdown?group=${group}&${rangeQS(range)}${deliveryQS(includeDelivery)}`,
    )
    .then((r) => r.data);

export const fetchBasket = (
  range: RangeSel,
  group: DishGroupBy = "category",
  includeDelivery = true,
  top = 14,
): Promise<Basket> =>
  api
    .get<Basket>(
      `/api/dishes/basket?group=${group}&top=${top}&${rangeQS(range)}${deliveryQS(includeDelivery)}`,
    )
    .then((r) => r.data);

export const fetchCheckComposition = (
  range: RangeSel,
  includeDelivery = true,
): Promise<CheckComposition> =>
  api
    .get<CheckComposition>(
      `/api/dishes/check-composition?${rangeQS(range)}${deliveryQS(includeDelivery)}`,
    )
    .then((r) => r.data);

export const fetchCheckDistribution = (
  range: RangeSel,
  includeDelivery = true,
): Promise<CheckDistribution> =>
  api
    .get<CheckDistribution>(
      `/api/dishes/check-distribution?${rangeQS(range)}${deliveryQS(includeDelivery)}`,
    )
    .then((r) => r.data);

export const fetchCheckFullness = (
  range: RangeSel,
  includeDelivery = true,
): Promise<CheckFullness> =>
  api
    .get<CheckFullness>(
      `/api/dishes/check-fullness?${rangeQS(range)}${deliveryQS(includeDelivery)}`,
    )
    .then((r) => r.data);
