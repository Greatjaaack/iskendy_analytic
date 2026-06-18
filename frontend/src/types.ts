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
  prev: {
    total_revenue: number | null;
    total_checks: number | null;
    avg_check: number | null;
  };
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

export interface PrevDay {
  date: string;
  total_sum: number | null;
  temp_max: number | null;
}

export interface RevenueResponse {
  period: Period | "custom";
  date_from: string;
  date_to: string;
  summary: RevenueSummary;
  data: RevenueDay[];
  prev_data: PrevDay[];
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

// Выручка/часы в разрезе каналов (зал/с собой/доставка). Ключи каналов — в channels.
export interface ChannelDay {
  date: string;
  day_of_week: string;
  total: number;
  [channel: string]: number | string;
}
export interface RevenueByChannel {
  period: Period | "custom";
  date_from: string;
  date_to: string;
  channels: string[];
  data: ChannelDay[];
}
export interface ChannelHour {
  hour: number;
  label: string;
  total: number;
  [channel: string]: number | string;
}
export interface HourlyByChannel {
  period: Period | "custom";
  date_from: string;
  date_to: string;
  channels: string[];
  data: ChannelHour[];
}

// Состав чека (#5): средняя доля категорий в чеке (по кол-ву и выручке), период + часы.
export interface CompositionShare {
  qty: number;
  rev: number;
}
export interface CompositionBucket {
  checks: number;
  by: Record<string, CompositionShare>;
}
export interface CheckComposition {
  period: Period | "custom";
  date_from: string;
  date_to: string;
  categories: string[];
  total: CompositionBucket;
  hourly: ({ hour: number; label: string } & CompositionBucket)[];
}

// Наполненность чеков (#6): распределение по числу позиций (1/2/3/4+) по часам.
export interface CheckFullness {
  period: Period | "custom";
  date_from: string;
  date_to: string;
  buckets: string[];
  total: Record<string, number>;
  data: ({ hour: number; label: string; total: number } & Record<string, number>)[];
}

// Разрез блюдо × канал обслуживания (#4). Ключи каналов («в зале»/«с собой»/«доставка»)
// приходят в channels; значения по ним — числа (кол-во).
export interface ServiceBreakdownRow {
  name: string;
  total: number;
  revenue: number;
  [channel: string]: number | string;
}

export interface ServiceBreakdown {
  group_by: DishGroupBy;
  period: Period | "custom";
  date_from: string;
  date_to: string;
  channels: string[];
  data: ServiceBreakdownRow[];
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

export interface SupplierContact {
  id: number;
  contact_person: string;
  phone: string;
  whatsapp: string;
  telegram: string;
  email: string;
  comment: string;
}

export interface ContactInput {
  contact_person?: string;
  phone?: string;
  whatsapp?: string;
  telegram?: string;
  email?: string;
  comment?: string;
}

export interface SupplierBrief {
  id: number;
  name: string;
  address: string;
  min_delivery: string;
  comment: string;
  contacts: SupplierContact[];
  products: number;
}

export interface SupplierProduct {
  ingredient_id: number;
  price_id: number;
  name: string;
  brand: string;
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
