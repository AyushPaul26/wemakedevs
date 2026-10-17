import {
  createContext,
  useCallback,
  useContext,
  useState,
  type Dispatch,
  type SetStateAction,
  type ReactNode,
} from "react";
type Drafts = Record<string, unknown>;
const DraftContext = createContext<{
  values: Drafts;
  setValues: Dispatch<SetStateAction<Drafts>>;
} | null>(null);
/** Memory-only drafts share the authenticated workspace's lifetime. */
export function SessionDraftProvider({ children }: { children: ReactNode }) {
  const [values, setValues] = useState<Drafts>({});
  return (
    <DraftContext.Provider value={{ values, setValues }}>
      {children}
    </DraftContext.Provider>
  );
}
export function useSessionDraft<T>(key: string, initial: T) {
  const context = useContext(DraftContext);
  const [fallback, setFallback] = useState(initial);
  const values = context?.values;
  const setValues = context?.setValues;
  const value =
    values && Object.prototype.hasOwnProperty.call(values, key)
      ? (values[key] as T)
      : initial;
  const setValue = useCallback(
    (next: SetStateAction<T>) =>
      setValues?.((current) => {
        const previous = Object.prototype.hasOwnProperty.call(current, key)
          ? (current[key] as T)
          : initial;
        const resolved =
          typeof next === "function"
            ? (next as (value: T) => T)(previous)
            : next;
        return Object.is(previous, resolved)
          ? current
          : { ...current, [key]: resolved };
      }),
    [key, setValues, initial],
  );
  return context
    ? ([value, setValue] as const)
    : ([fallback, setFallback] as const);
}
