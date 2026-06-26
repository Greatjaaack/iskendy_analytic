// Функции авторизации (вход/выход/проверка). Вынесены из auth.tsx, чтобы тот
// экспортировал только компонент RequireAuth (требование react-refresh: файл с
// компонентами не должен экспортировать ещё и обычные функции).
import { api } from "./api";
import { clearToken, getToken, setToken } from "./token";

/** Войти: запросить токен и сохранить его. Бросает axios-ошибку при неверных данных. */
export async function login(username: string, password: string): Promise<void> {
  const { data } = await api.post<{ token: string; username: string }>("/api/auth/login", {
    username,
    password,
  });
  setToken(data.token);
}

/** Выйти: стереть токен и вернуться на экран входа. */
export function logout(): void {
  clearToken();
  window.location.href = "/login";
}

export const isAuthed = (): boolean => !!getToken();
