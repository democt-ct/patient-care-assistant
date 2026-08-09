import { createContext, useContext, type Dispatch } from 'react';
import type { AppAction, AppState } from '../types';

export interface AppContextType {
  state: AppState;
  dispatch: Dispatch<AppAction>;
}

export const AppContext = createContext<AppContextType | null>(null);

export function useAppState(): AppContextType {
  const context = useContext(AppContext);
  if (!context) throw new Error('useAppState must be used within AppProvider');
  return context;
}
