import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import type { ReactNode } from 'react';

import { api, clearToken, getToken, type UserOut } from '@/api/platform';

interface AuthState {
	user: UserOut | null;
	ready: boolean;
	login: (username: string, password?: string) => Promise<void>;
	logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
	const [user, setUser] = useState<UserOut | null>(null);
	const [ready, setReady] = useState(false);

	useEffect(() => {
		if (!getToken()) {
			setReady(true);
			return;
		}
		api
			.me()
			.then(setUser)
			.catch(() => clearToken())
			.finally(() => setReady(true));
	}, []);

	const login = useCallback(async (username: string, password?: string) => {
		const res = await api.login(username, password);
		clearToken();
		// setToken after clearing, in case a stale token lingers.
		localStorage.setItem('platform_token', res.access_token);
		setUser(res.user);
	}, []);

	const logout = useCallback(() => {
		clearToken();
		setUser(null);
		window.location.href = '/login';
	}, []);

	return <AuthContext.Provider value={{ user, ready, login, logout }}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
	const ctx = useContext(AuthContext);
	if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
	return ctx;
}
