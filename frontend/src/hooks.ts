import {
  useQuery,
  type UseQueryOptions,
  type UseQueryResult,
} from "@tanstack/react-query";
import { REFETCH_INTERVAL_MS } from "./constants";

/**
 * useQuery для «живых» виджетов дашборда: автоматически поллит сервер раз в
 * REFETCH_INTERVAL_MS. Справочные/CRUD-экраны (поставщики, ТТК, номенклатура,
 * редактор плана) сознательно НЕ поллят — там используется обычный useQuery.
 * Интервал можно переопределить в точке вызова (например, refetchInterval: false).
 */
export function useLiveQuery<
  TQueryFnData,
  TError = Error,
  TData = TQueryFnData,
>(
  options: UseQueryOptions<TQueryFnData, TError, TData>,
): UseQueryResult<TData, TError> {
  return useQuery({ refetchInterval: REFETCH_INTERVAL_MS, ...options });
}
