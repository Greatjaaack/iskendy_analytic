// Хранение JWT сессии в localStorage. Выделено отдельно от api.ts и auth.tsx,
// чтобы перехватчики axios и guard-компонент не образовывали циклический импорт.

const TOKEN_KEY = "iskendy_auth_token";

export const getToken = (): string | null => localStorage.getItem(TOKEN_KEY);
export const setToken = (t: string): void => localStorage.setItem(TOKEN_KEY, t);
export const clearToken = (): void => localStorage.removeItem(TOKEN_KEY);
