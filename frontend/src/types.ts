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

// ── Ежедневный операционный отчёт (дни × дейпарты), аналог Excel-свода «ОП» ──
export interface OpsCell {
  revenue: number;
  checks: number;
  guests: number;
  avg_check: number;
  cost: number;
  food_cost_pct: number | null; // null — нет блюд с ТТК-привязкой
  coverage: number; // % выручки окна, покрытый ТТК (надёжность кост%)
}
export interface OpsAvg {
  revenue: number;
  checks: number;
  guests: number;
  avg_check: number;
}
export interface OpsCatCell {
  revenue: number;
  cost: number;
  food_cost_pct: number | null;
  coverage: number; // % выручки группы, покрытый ТТК
  revenue_share: number; // доля группы в выручке (дейпарта или периода)
}
export interface OpsPlan {
  revenue: number;
  avg_check: number;
  guests: number;
}
export interface OpsPlanPct {
  revenue: number | null;
  avg_check: number | null;
  guests: number | null;
}
export interface OpsDaypart {
  key: string;
  label: string;
  range: string;
  cells: Record<string, OpsCell>; // дата ISO → метрики
  total: OpsCell; // Факт за период
  avg_per_day: OpsAvg; // Среднее на активный день
  active_days: number;
  revenue_share: number; // доля дейпарта в выручке периода, %
  categories: Record<string, OpsCatCell>; // группа (Еда/Напитки/Алкоголь) → food cost
  plan: OpsPlan; // план на период (норма × число дней)
  plan_pct: OpsPlanPct; // % выполнения плана по метрикам
}
export interface OpsDay {
  date: string;
  dom: number; // число месяца
  weekday: string; // «Пн» … «Вс»
}
export interface OpsReport {
  period: Period | "custom";
  date_from: string;
  date_to: string;
  days: OpsDay[];
  dayparts: OpsDaypart[];
  totals: {
    cells: Record<string, OpsCell>;
    total: OpsCell;
    avg_per_day: OpsAvg;
    plan: OpsPlan;
    plan_pct: OpsPlanPct;
  };
  category_groups: string[]; // присутствующие группы (Еда / Напитки / …)
  category_totals: Record<string, OpsCatCell>; // итог по группе за период
  has_plan: boolean; // задан ли план (хотя бы одна норма выручки > 0)
}

// ── Слой плана: матрица (дейпарт × группа дня недели) дневных норм ──
export interface PlanCell {
  revenue: number;
  avg_check: number;
  guests: number;
}
export interface PlanMatrix {
  dayparts: { key: string; label: string; range: string }[];
  weekday_groups: { key: string; label: string }[];
  cells: Record<string, PlanCell>; // "<дейпарт>|<группа>" → норма на день
  has_plan: boolean;
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

// Структура выручки по способам оплаты (Карта/Наличные/Агрегатор): доли за период + тренд.
export interface PaymentTotal {
  group: string;
  amount: number;
  share: number;
  checks: number;
  check_share: number;
}
export interface PaymentDay {
  date: string;
  [group: string]: string | number;
}
export interface PaymentStructure {
  period: Period | "custom";
  date_from: string;
  date_to: string;
  groups: string[];
  totals: PaymentTotal[];
  total_amount: number;
  total_checks: number;
  daily: PaymentDay[];
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

// ─── P&L дня ─────────────────────────────────────────────────────────────────
export type PnlRating = "green" | "yellow" | "red" | null;

export interface PnlLine {
  key: string;
  label: string;
  kind: "money" | "metric";
  rub?: number;
  pct?: number;
  value?: number | null;
  unit?: "rub" | "num" | "pct";
  rating: PnlRating;
}

export interface PnlSection {
  key: string;
  label: string;
  lines: PnlLine[];
}

export interface PnlBreakeven {
  cm_ratio: number;
  fixed_month: number;
  revenue_month: number | null;
  revenue_day: number | null;
  avg_rev_day: number;
}

/** Метрики одного дня подневной матрицы P&L — все статьи ₽ отдельными ключами
 *  (зал/доставка не смешиваются). Долю от выручки дня фронт считает сам. */
export interface PnlDay {
  date: string;
  day_of_week: string;
  revenue: number;
  revenue_hall: number;
  revenue_delivery: number;
  checks: number;
  checks_hall: number;
  checks_delivery: number;
  agg_revenue: number;
  food_cost: number;
  writeoffs: number;
  packaging: number;
  chemicals: number;
  supplies: number;
  cogs: number;
  labor: number;
  rent: number;
  utilities: number;
  marketing: number;
  admin_fot: number;
  other_opex: number;
  contingency: number;
  cap_reserve: number;
  tax: number;
  aggregator: number;
  total_expenses: number;
  ebitda: number;
  net_profit: number;
  ebitda_margin: number;
  food_cost_pct: number;
  /** Сопоставимый день пред. периода — тот же день недели (пн↔пн, чт↔чт…). */
  prev: PnlDay | null;
}

/** Ключ статьи-строки подневной матрицы — совпадает с ключом ₽ в PnlDay. */
export type PnlDayKey =
  | "revenue" | "revenue_hall" | "revenue_delivery" | "agg_revenue"
  | "food_cost" | "writeoffs" | "packaging" | "cogs"
  | "labor" | "chemicals" | "supplies"
  | "rent" | "utilities" | "admin_fot" | "other_opex" | "contingency" | "cap_reserve"
  | "tax" | "aggregator" | "total_expenses" | "ebitda" | "net_profit";

// ─── Дневные затраты (редактор «Затраты по дням») ─────────────────────────────
export interface PnlDayCostRow {
  date: string;
  day_of_week: string;
  has_row: boolean;
  writeoffs: number;
  packaging: number;
  chemicals: number;
  supplies: number;
}

export interface PnlDayCostsResponse {
  date_from: string;
  date_to: string;
  fields: { key: string; label: string }[];
  days: PnlDayCostRow[];
}

export interface PnlPrevSummary {
  date_from: string;
  date_to: string;
  revenue: number;
  revenue_hall: number;
  revenue_delivery: number;
  checks: number;
  ebitda: number;
  ebitda_margin: number;
  net_profit: number;
  net_margin: number;
}

export interface PnlReport {
  period: string;
  date_from: string;
  date_to: string;
  active_days: number;
  has_costs: boolean;
  labor_missing_days: number; // дней с выручкой, но без заведённого ФОТ (график смен)
  costs_missing_months: string[]; // «YYYY-MM» месяцев периода без постоянных затрат
  revenue: number;
  ebitda: number;
  ebitda_margin: number;
  ebitda_rating: PnlRating;
  net_profit: number;
  net_margin: number;
  net_rating: PnlRating;
  breakeven: PnlBreakeven;
  prev_summary: PnlPrevSummary | null;
  daily: PnlDay[];
  sections: PnlSection[];
}

export interface PnlCostsResponse {
  values: Record<string, number>;
  manual_fields: { key: string; label: string }[];
  rate_fields: { key: string; label: string }[];
}

// ─── График и ФОТ ────────────────────────────────────────────────────────────
export type LaborGroup = "operational" | "admin";
export type PayType = "shift" | "month";

export interface Employee {
  id: number;
  name: string;
  role: string;
  labor_group: LaborGroup;
  pay_type: PayType;
  rate: number;
  active: boolean;
}

export interface ShiftEntry {
  employee_id: number;
  date: string;
}

export interface LaborSummary {
  year: number;
  month: number;
  operational: number;
  admin: number;
  total: number;
}
