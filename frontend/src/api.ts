// HTTP-клиент и вызовы API. Доменные типы — в types.ts (реэкспортятся ниже,
// чтобы компоненты могли импортировать и функцию, и тип из одного места "../api").
import axios from "axios";

import type {
  CheckDistribution,
  DishGroupBy,
  DishMapping,
  DishResponse,
  HourlyBreakdown,
  HourlyResponse,
  IngredientBrief,
  IngredientCard,
  RangeSel,
  RevenueResponse,
  SupplierBrief,
  SupplierCard,
  SupplierInput,
  TtkBrief,
  TtkCard,
} from "./types";

export type * from "./types";

// VITE_API_URL не задан → дефолт для локальной разработки (vite :5173, backend :8000).
// В Docker-сборке прокидывается пустая строка → относительные пути, nginx проксирует /api.
const BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export const api = axios.create({ baseURL: BASE });

/** Query-строка для API из выбора диапазона (пресет или произвольные даты). */
export const rangeQS = (r: RangeSel): string =>
  "from" in r ? `date_from=${r.from}&date_to=${r.to}` : `period=${r.period}`;

/** Стабильный ключ диапазона для queryKey React Query. */
export const rangeKey = (r: RangeSel): string =>
  "from" in r ? `${r.from}..${r.to}` : r.period;

// ---------- Выручка / часы ----------

export const fetchRevenue = (range: RangeSel): Promise<RevenueResponse> =>
  api.get<RevenueResponse>(`/api/revenue?${rangeQS(range)}`).then((r) => r.data);

export const fetchHourly = (range: RangeSel): Promise<HourlyResponse> =>
  api.get<HourlyResponse>(`/api/revenue/hourly?${rangeQS(range)}`).then((r) => r.data);

export const triggerSync = () => api.post("/api/sync");

// ---------- Продажи блюд ----------

export const fetchDishes = (range: RangeSel, groupBy: DishGroupBy = "dish"): Promise<DishResponse> =>
  api.get<DishResponse>(`/api/dishes?${rangeQS(range)}&group_by=${groupBy}`).then((r) => r.data);

export const fetchCheckDistribution = (range: RangeSel): Promise<CheckDistribution> =>
  api.get<CheckDistribution>(`/api/dishes/check-distribution?${rangeQS(range)}`).then((r) => r.data);

export const fetchHourlyBreakdown = (range: RangeSel, group: DishGroupBy): Promise<HourlyBreakdown> =>
  api
    .get<HourlyBreakdown>(`/api/dishes/hourly-breakdown?group=${group}&${rangeQS(range)}`)
    .then((r) => r.data);

// ---------- Поставщики ----------

export const fetchSuppliers = (): Promise<SupplierBrief[]> =>
  api.get<SupplierBrief[]>("/api/suppliers").then((r) => r.data);

export const fetchSupplier = (id: number): Promise<SupplierCard> =>
  api.get<SupplierCard>(`/api/suppliers/${id}`).then((r) => r.data);

export const createSupplier = (data: SupplierInput): Promise<SupplierBrief> =>
  api.post<SupplierBrief>("/api/suppliers", data).then((r) => r.data);

export const updateSupplier = (id: number, data: SupplierInput): Promise<SupplierBrief> =>
  api.put<SupplierBrief>(`/api/suppliers/${id}`, data).then((r) => r.data);

export const uploadSupplierFile = (id: number, file: File, fileType = "other") => {
  const form = new FormData();
  form.append("file", file);
  form.append("file_type", fileType);
  return api.post(`/api/suppliers/${id}/files`, form).then((r) => r.data);
};

export const supplierFileUrl = (supplierId: number, fileId: number) =>
  `${BASE}/api/suppliers/${supplierId}/files/${fileId}`;

// ---------- Номенклатура / ТТК ----------

export const fetchIngredients = (): Promise<IngredientBrief[]> =>
  api.get<IngredientBrief[]>("/api/ingredients").then((r) => r.data);

export const fetchIngredient = (id: number): Promise<IngredientCard> =>
  api.get<IngredientCard>(`/api/ingredients/${id}`).then((r) => r.data);

export const fetchTtkList = (): Promise<TtkBrief[]> =>
  api.get<TtkBrief[]>("/api/ttk").then((r) => r.data);

export const fetchTtk = (id: number): Promise<TtkCard> =>
  api.get<TtkCard>(`/api/ttk/${id}`).then((r) => r.data);

export const runImport = () => api.post("/api/import/ttk-matrix").then((r) => r.data);

// ---------- Привязка блюдо ↔ ТТК ----------

export const fetchDishMappings = (): Promise<DishMapping[]> =>
  api.get<DishMapping[]>("/api/dish-mappings").then((r) => r.data);

export const saveDishMapping = (sale_name: string, ttk_id: number) =>
  api.post("/api/dish-mappings", { sale_name, ttk_id }).then((r) => r.data);

export const deleteDishMapping = (id: number) =>
  api.delete(`/api/dish-mappings/${id}`).then((r) => r.data);
