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
  temp_max: number | null; // дневная температура (ночную не показываем)
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

// Свод выручки по дням недели (#7): агрегат дней одного дня недели за период.
export interface WeekdayRow {
  weekday: string; // Пн … Вс
  days: number; // сколько таких дней недели в периоде
  revenue: number; // суммарная выручка
  avg_day_revenue: number; // средняя выручка за такой день
  checks: number;
  avg_check: number;
  food_cost_pct: number;
}

export interface WeekdaySummary {
  period: Period | "custom";
  date_from: string;
  date_to: string;
  data: WeekdayRow[];
}

// Свод выручки по дейпартам (операционные окна дня: Завтрак/Ланч/Полдник/Ужин/Ночь).
export interface DaypartRow {
  key: string;
  label: string; // Завтрак … Ночь
  range: string; // «08–12»
  revenue: number;
  checks: number;
  avg_check: number;
  revenue_share: number; // % дейпарта в выручке периода
}

export interface DaypartSummary {
  period: Period | "custom";
  date_from: string;
  date_to: string;
  data: DaypartRow[];
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
  has_cost: boolean; // нашлась ли порционная с/с (ТТК-привязка)
  cost_pct: number | null; // с/с в % (себестоимость / выручка); null — нет с/с
  margin_pct: number | null; // null — нет с/с (не показываем мнимую 100% маржу)
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

// KPI в разрезе доставка / не доставка (для верхних карточек — брутто-суммы по каналам).
export interface ChannelKpi {
  revenue: number;
  checks: number;
  avg_check: number;
}
export interface KpiByChannel {
  period: Period | "custom";
  date_from: string;
  date_to: string;
  delivery: ChannelKpi;
  other: ChannelKpi;
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
  category?: string; // присутствует в режиме group=dish (для drill-down «категория → блюда»)
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

// ---------- Матрица сочетаемости (market basket) ----------

export interface BasketPair {
  a: string; // сильная позиция пары (чаще встречается)
  b: string;
  count: number; // в скольких чеках встречались обе
  support: number; // % чеков с обеими
  confidence: number; // % чеков с B среди чеков с A
}

export interface Basket {
  period: Period | "custom";
  date_from: string;
  date_to: string;
  group_by: DishGroupBy;
  orders: number;
  labels: string[];
  freq: number[]; // число чеков с каждой позицией (для диагонали матрицы)
  matrix: number[][]; // matrix[i][j] = чеков с обеими i и j
  pairs: BasketPair[];
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
