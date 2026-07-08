import { useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

import type { Employee } from "../api";
import {
  fetchEmployees,
  createEmployee,
  updateEmployee,
  deleteEmployee,
  fetchShifts,
  toggleShift,
  fetchLabor,
} from "../api";
import { fmtInt } from "../format";
import { COLORS, EMPLOYEE_ROLES } from "../constants";

const fmtRub = (n: number) => `${fmtInt(n)} ₽`;
const MONTHS = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"];
const WD = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];

const now = new Date();

/** График и ФОТ — сотрудники, ставки и смены. Таблица только для поваров:
 *  группа ФОТ всегда операционная, оплата всегда за смену (решение пользователя —
 *  административный ФОТ считается отдельно, вручную, как постоянные расходы в P&L). */
export function Schedule() {
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);
  const qc = useQueryClient();

  const empsQ = useQuery({ queryKey: ["employees"], queryFn: fetchEmployees });
  const shiftsQ = useQuery({ queryKey: ["shifts", year, month], queryFn: () => fetchShifts(year, month) });
  const laborQ = useQuery({ queryKey: ["labor", year, month], queryFn: () => fetchLabor(year, month) });

  const invalidateAll = () => {
    qc.invalidateQueries({ queryKey: ["employees"] });
    qc.invalidateQueries({ queryKey: ["shifts"] });
    qc.invalidateQueries({ queryKey: ["labor"] });
    qc.invalidateQueries({ queryKey: ["pnl"] });
  };

  const toggleMut = useMutation({
    mutationFn: ({ id, date }: { id: number; date: string }) => toggleShift(id, date),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["shifts", year, month] });
      qc.invalidateQueries({ queryKey: ["labor", year, month] });
      qc.invalidateQueries({ queryKey: ["pnl"] });
    },
  });

  const daysInMonth = new Date(year, month, 0).getDate();
  const days = useMemo(() => Array.from({ length: daysInMonth }, (_, i) => i + 1), [daysInMonth]);
  const dstr = (d: number) => `${year}-${String(month).padStart(2, "0")}-${String(d).padStart(2, "0")}`;

  const shiftSet = useMemo(
    () => new Set((shiftsQ.data ?? []).map((s) => `${s.employee_id}|${s.date}`)),
    [shiftsQ.data],
  );

  const emps = (empsQ.data ?? []).filter((e) => e.active);

  const shiftCount = (id: number) => days.filter((d) => shiftSet.has(`${id}|${dstr(d)}`)).length;

  return (
    <div className="page" style={{ minHeight: "100vh", background: COLORS.bg, color: "var(--text)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12, marginBottom: 20 }}>
        <div>
          <div style={{ fontSize: 22, fontWeight: 700 }}>График и ФОТ</div>
          <div style={{ color: COLORS.muted, fontSize: 13, marginTop: 2 }}>
            Повара, ставки и смены. ФОТ отсюда автоматически идёт в «P&L дня».
          </div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <select value={month} onChange={(e) => setMonth(Number(e.target.value))} style={inp}>
            {MONTHS.map((m, i) => <option key={i} value={i + 1}>{m}</option>)}
          </select>
          <select value={year} onChange={(e) => setYear(Number(e.target.value))} style={inp}>
            {[now.getFullYear() - 1, now.getFullYear()].map((y) => <option key={y} value={y}>{y}</option>)}
          </select>
        </div>
      </div>

      {laborQ.data && (
        <div style={{ marginBottom: 20 }}>
          <LaborCard label="ФОТ за месяц" value={laborQ.data.total} big />
        </div>
      )}

      {/* Сотрудники */}
      <div style={{ background: COLORS.card, borderRadius: 12, border: `1px solid ${COLORS.grid}`, padding: 16, marginBottom: 20 }}>
        <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 12 }}>Сотрудники</div>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13, minWidth: 420 }}>
            <thead>
              <tr style={{ color: COLORS.muted, fontSize: 11, textTransform: "uppercase" }}>
                <th style={thL}>Имя</th>
                <th style={thL}>Должность</th>
                <th style={thR}>Ставка</th>
                <th style={{ width: 90 }}></th>
              </tr>
            </thead>
            <tbody>
              {emps.map((e) => (
                <EmployeeRow key={e.id} emp={e} onChanged={invalidateAll} />
              ))}
              <AddEmployeeRow onAdded={invalidateAll} />
            </tbody>
          </table>
        </div>
      </div>

      {/* Сетка смен */}
      <div style={{ background: COLORS.card, borderRadius: 12, border: `1px solid ${COLORS.grid}`, padding: 16 }}>
        <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 4 }}>График смен — {MONTHS[month - 1]} {year}</div>
        <div style={{ fontSize: 12, color: COLORS.muted, marginBottom: 12 }}>
          Клик по клетке — отметить/снять выход. Стоимость смены = ставка сотрудника.
        </div>
        {emps.length === 0 ? (
          <div style={{ color: COLORS.muted, fontSize: 13 }}>Добавьте сотрудников, чтобы вести график.</div>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ borderCollapse: "collapse", fontSize: 12 }}>
              <thead>
                <tr>
                  <th style={{ ...gridSticky, textAlign: "left" }}>Сотрудник</th>
                  {days.map((d) => {
                    const wd = WD[(new Date(year, month - 1, d).getDay() + 6) % 7];
                    const weekend = wd === "Сб" || wd === "Вс";
                    return (
                      <th key={d} style={{ padding: "2px 0", width: 26, textAlign: "center", color: weekend ? COLORS.warn : COLORS.muted, fontWeight: 500 }}>
                        <div style={{ fontSize: 9 }}>{wd}</div>
                        <div>{d}</div>
                      </th>
                    );
                  })}
                  <th style={{ padding: "0 8px", textAlign: "right", color: COLORS.muted }}>Смен · ₽</th>
                </tr>
              </thead>
              <tbody>
                {emps.map((e) => {
                  const cnt = shiftCount(e.id);
                  return (
                    <tr key={e.id}>
                      <td style={{ ...gridSticky, textAlign: "left", whiteSpace: "nowrap" }}>{e.name}</td>
                      {days.map((d) => {
                        const on = shiftSet.has(`${e.id}|${dstr(d)}`);
                        return (
                          <td key={d} style={{ padding: 1, textAlign: "center" }}>
                            <button
                              onClick={() => toggleMut.mutate({ id: e.id, date: dstr(d) })}
                              title={`${e.name} · ${d} ${MONTHS[month - 1]}`}
                              style={{
                                width: 22, height: 22, borderRadius: 4, cursor: "pointer",
                                border: `1px solid ${COLORS.grid}`,
                                background: on ? COLORS.primary : "transparent",
                                color: on ? "#fff" : "transparent", fontSize: 11, lineHeight: 1,
                              }}
                            >
                              ✓
                            </button>
                          </td>
                        );
                      })}
                      <td style={{ padding: "0 8px", textAlign: "right", whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums" }}>
                        <b>{cnt}</b> · {fmtRub(cnt * e.rate)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function LaborCard({ label, value, big }: { label: string; value: number; big?: boolean }) {
  return (
    <div style={{ background: COLORS.card, borderRadius: 12, padding: "14px 20px", minWidth: 170, border: `1px solid ${COLORS.grid}` }}>
      <div style={{ color: COLORS.muted, fontSize: 12 }}>{label}</div>
      <div style={{ fontSize: big ? 26 : 20, fontWeight: 700, marginTop: 4 }}>{fmtRub(value)}</div>
    </div>
  );
}

// Группа ФОТ и оплата у поваров фиксированы (операционный / за смену) — не выбираются в UI.
const emptyDraft = { name: "", role: EMPLOYEE_ROLES[0] as string, labor_group: "operational" as const, pay_type: "shift" as const, rate: 0 };

function AddEmployeeRow({ onAdded }: { onAdded: () => void }) {
  const [d, setD] = useState({ ...emptyDraft });
  const mut = useMutation({
    mutationFn: () => createEmployee(d),
    onSuccess: () => { setD({ ...emptyDraft }); onAdded(); },
  });
  return (
    <tr style={{ borderTop: `1px solid ${COLORS.grid}`, background: "rgba(99,102,241,0.05)" }}>
      <td style={td}><input placeholder="Имя" value={d.name} onChange={(e) => setD({ ...d, name: e.target.value })} style={cellInp} /></td>
      <td style={td}>
        <select value={d.role} onChange={(e) => setD({ ...d, role: e.target.value })} style={cellInp}>
          {EMPLOYEE_ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
      </td>
      <td style={td}><input type="number" value={d.rate} onChange={(e) => setD({ ...d, rate: Number(e.target.value) || 0 })} style={{ ...cellInp, textAlign: "right" }} /></td>
      <td style={td}>
        <button onClick={() => d.name.trim() && mut.mutate()} disabled={mut.isPending} style={{ ...miniBtn, background: COLORS.primary, color: "#fff", border: "none" }}>
          + Добавить
        </button>
      </td>
    </tr>
  );
}

function EmployeeRow({ emp, onChanged }: { emp: Employee; onChanged: () => void }) {
  const [d, setD] = useState<Employee>(emp);
  const dirty = d.name !== emp.name || d.role !== emp.role || d.rate !== emp.rate;
  const saveMut = useMutation({ mutationFn: () => updateEmployee(emp.id, d), onSuccess: onChanged });
  const delMut = useMutation({ mutationFn: () => deleteEmployee(emp.id), onSuccess: onChanged });
  return (
    <tr style={{ borderTop: `1px solid ${COLORS.grid}` }}>
      <td style={td}><input value={d.name} onChange={(e) => setD({ ...d, name: e.target.value })} style={cellInp} /></td>
      <td style={td}>
        <select value={d.role} onChange={(e) => setD({ ...d, role: e.target.value })} style={cellInp}>
          {EMPLOYEE_ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
      </td>
      <td style={td}><input type="number" value={d.rate} onChange={(e) => setD({ ...d, rate: Number(e.target.value) || 0 })} style={{ ...cellInp, textAlign: "right" }} /></td>
      <td style={{ ...td, whiteSpace: "nowrap" }}>
        {dirty && (
          <button onClick={() => saveMut.mutate()} style={{ ...miniBtn, background: COLORS.good, color: "#fff", border: "none", marginRight: 4 }}>✓</button>
        )}
        <button onClick={() => delMut.mutate()} title="Удалить" style={{ ...miniBtn, color: COLORS.bad }}>✕</button>
      </td>
    </tr>
  );
}

const inp: React.CSSProperties = { padding: "6px 10px", borderRadius: 8, border: `1px solid ${COLORS.grid}`, background: COLORS.card, color: "var(--text)", fontSize: 13 };
const cellInp: React.CSSProperties = { width: "100%", padding: "5px 8px", borderRadius: 6, border: `1px solid ${COLORS.grid}`, background: COLORS.bg, color: "var(--text)", fontSize: 13, boxSizing: "border-box" };
const td: React.CSSProperties = { padding: "5px 6px" };
const thL: React.CSSProperties = { textAlign: "left", padding: "6px", fontWeight: 500 };
const thR: React.CSSProperties = { textAlign: "right", padding: "6px", fontWeight: 500 };
const miniBtn: React.CSSProperties = { padding: "5px 9px", borderRadius: 6, border: `1px solid ${COLORS.grid}`, background: "transparent", fontSize: 12, cursor: "pointer" };
const gridSticky: React.CSSProperties = { position: "sticky", left: 0, background: COLORS.card, padding: "4px 10px 4px 4px", zIndex: 1 };
