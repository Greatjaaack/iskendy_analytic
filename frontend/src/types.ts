// Доменные типы API (DTO бэкенда). Только типы — без логики и запросов.
// Вызовы и axios-инстанс — в api.ts (он реэкспортит эти типы для удобства импорта).

export type Period = "day" | "week" | "month";

// Выбор диапазона: либо пресет (день/неделя/месяц), либо произвольный диапазон дат.
export type RangeSel = { period: Period } | { from: string; to: string };

// ---------- Выручка ----------

export interface RevenueSummary {
  total_revenue: number;
  avg_daily_revenue: number;
  total_checks: number;
  avg_check: number;
  total_cost: number;
  food_cost_pct: number;
}

export interface DayWeather {
  temp_max: number | null;
  temp_min: number | null;
  weather_code: number | null;
}

export interface RevenueDay {
  date: string;
  day_of_week: string;
  total_sum: number;
  discount_sum: number;
  refund_count: number;
  cost_sum: number;
  check_count: number;
  avg_check: number;
  food_cost_pct: number;
  weather: DayWeather | null;
}

export interface RevenueResponse {
  period: Period | "custom";
  date_from: string;
  date_to: string;
  summary: RevenueSummary;
  data: RevenueDay[];
}

// ---------- Продажи блюд ----------

export type DishGroupBy = "dish" | "category";

export interface DishRow {
  key: string;
  name: string;
  group_name: string;
  channel: string; // "доставка" для позиций с постфиксом _д, иначе ""
  quantity: number;
  revenue: number;
  cost_sum: number;
  cost_pct: number; // с/с в % (себестоимость / выручка)
  margin_pct: number;
  revenue_share: number;
  qty_share: number;
}

export interface DishResponse {
  period: Period | "custom";
  group_by: DishGroupBy;
  date_from: string;
  date_to: string;
  totals: { revenue: number; quantity: number };
  data: DishRow[];
}

// ---------- Почасовые продажи ----------

export interface HourRow {
  hour: number;
  label: string;
  revenue: number;
  checks: number;
  avg_check: number;
}

export interface HourlyResponse {
  period: Period;
  date_from: string;
  date_to: string;
  data: HourRow[];
}

export interface HourItem {
  name: string;
  revenue: number;
  quantity: number;
}

export interface HourBreakdownRow {
  hour: number;
  label: string;
  revenue: number;
  quantity: number;
  items: HourItem[];
}

export interface HourlyBreakdown {
  group_by: DishGroupBy;
  period: Period | "custom";
  date_from: string;
  date_to: string;
  data: HourBreakdownRow[];
}

// ---------- Распределение чеков по типу обслуживания ----------

export interface CheckTypeRow {
  type: string; // Доставка / В зале / С собой
  count: number;
  share: number; // % от всех чеков
}

export interface CheckDistribution {
  period: Period | "custom";
  date_from: string;
  date_to: string;
  total: number;
  data: CheckTypeRow[];
}

// ---------- Поставщики ----------

export interface SupplierBrief {
  id: number;
  name: string;
  contact_person: string;
  phone: string;
  address: string;
  min_delivery: string;
  comment: string;
  products: number;
}

export interface SupplierProduct {
  ingredient_id: number;
  name: string;
  unit: string;
  pack_size: number | null;
  pack_price: number | null;
  unit_price: number | null;
  price_date: string | null;
}

export interface SupplierFileInfo {
  id: number;
  filename: string;
  file_type: string;
  uploaded_at: string;
}

export interface SupplierCard extends SupplierBrief {
  products_list: SupplierProduct[];
  files: SupplierFileInfo[];
}

export interface SupplierInput {
  name: string;
  contact_person?: string;
  phone?: string;
  address?: string;
  min_delivery?: string;
  comment?: string;
}

// ---------- Номенклатура / ТТК ----------

export interface IngredientBrief {
  id: number;
  name: string;
  unit: string;
  iiko_product_id: string | null;
  prices: number;
}

export interface IngredientPrice {
  supplier_id: number;
  supplier: string;
  pack_size: number | null;
  pack_price: number | null;
  unit_price: number | null;
  price_date: string | null;
}

export interface IngredientCard {
  id: number;
  name: string;
  unit: string;
  iiko_product_id: string | null;
  prices: IngredientPrice[];
  used_in: { id: number; name: string; category: string }[];
}

export interface TtkBrief {
  id: number;
  name: string;
  category: string;
  is_semi: boolean;
  yield_qty: number | null;
  yield_unit: string;
  cost_total: number;
}

export interface TtkLine {
  id: number;
  raw_name: string;
  ingredient_id: number | null;
  child_ttk_id: number | null;
  child_ttk_name: string | null;
  gross: number | null;
  net: number | null;
  unit: string;
  waste_pct: number | null;
  cost_rub: number | null;
}

export interface TtkCard extends TtkBrief {
  lines: TtkLine[];
}

// Привязка проданное блюдо ↔ ТТК (источник с/с по блюду)
export interface DishMapping {
  id: number;
  sale_name: string;
  ttk_id: number;
  ttk_name: string | null;
  cost_full: number | null;
}
