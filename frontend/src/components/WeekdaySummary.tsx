import { useLiveQuery } from "../hooks";
import { fetchRevenueByWeekday, rangeKey, type RangeSel } from "../api";
import { COLORS, WEEKDAYS_ALL, weekdayGroup } from "../constants";
import { fmtInt } from "../format";

interface Props {
  range: RangeSel;
  withDelivery?: boolean;
}

/** Свод выручки по дням недели (#7): суммирует дни одного дня недели за период.
 *  Видно, какие дни недели «вытягивают» выручку. Данные — `/api/revenue/by-weekday`.
 *  Порядок строк всегда Пн→Вс; строки окрашены по группе дня недели (как «Выручка по дням»). */
export function WeekdaySummary({ range, withDelivery = true }: Props) {
  const q = useLiveQuery({
    queryKey: ["revenue-by-weekday", rangeKey(range), withDelivery],
    queryFn: () => fetchRevenueByWeekday(range, withDelivery),
  });

  // Фиксированный порядок Пн→Вс независимо от того, как пришло с бэкенда.
  const data = q.data?.data ?? [];
  const rows = WEEKDAYS_ALL.map((wd) => data.find((r) => r.weekday === wd)).filter(
    (r): r is NonNullable<typeof r> => r != null,
  );

  return (
    <div style={{ background: COLORS.card, borderRadius: 12, padding: "20px 24px" }}>
      <div style={{ color: "var(--text)", fontWeight: 600, marginBottom: 12 }}>
        Свод по дням недели
      </div>

      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ color: COLORS.muted, textAlign: "left" }}>
              <th style={th}>День недели</th>
              <th style={{ ...th, textAlign: "right" }}>Дней</th>
              <th style={{ ...th, textAlign: "right" }}>Выручка</th>
              <th style={{ ...th, textAlign: "right" }}>Ср. за день</th>
              <th style={{ ...th, textAlign: "right" }}>Чеки</th>
              <th style={{ ...th, textAlign: "right" }}>Ср. чек</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const color = weekdayGroup(r.weekday).color;
              return (
                <tr key={r.weekday} style={{ borderTop: `1px solid ${COLORS.grid}` }}>
                  <td style={{ ...td, fontWeight: 600 }}>
                    <span style={{
                      display: "inline-block", width: 8, height: 8, borderRadius: 2,
                      marginRight: 8, background: color, verticalAlign: "middle",
                    }} />
                    {r.weekday}
                  </td>
                  <td style={tdR}>{r.days}</td>
                  <td style={tdR}>{fmtInt(r.revenue)}</td>
                  <td style={tdR}>{fmtInt(r.avg_day_revenue)}</td>
                  <td style={tdR}>{r.checks}</td>
                  <td style={tdR}>{fmtInt(r.avg_check)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {q.isLoading && <div style={{ color: COLORS.muted, textAlign: "center", padding: 24 }}>Загрузка…</div>}
        {!q.isLoading && rows.length === 0 && (
          <div style={{ color: COLORS.muted, textAlign: "center", padding: 24 }}>Нет данных</div>
        )}
      </div>
    </div>
  );
}

const td: React.CSSProperties = { padding: "8px 12px" };
const tdR: React.CSSProperties = { padding: "8px 12px", textAlign: "right" };
const th: React.CSSProperties = { padding: "8px 12px", whiteSpace: "nowrap" };
