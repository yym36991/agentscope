import { Loader2 } from 'lucide-react';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

import { useAuth } from '@/auth';
import { Button } from '@/components/ui/button';
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

export function LoginPage() {
	const { login } = useAuth();
	const navigate = useNavigate();
	const [username, setUsername] = useState('');
	const [password, setPassword] = useState('');
	const [busy, setBusy] = useState(false);

	const submit = async (e: React.FormEvent) => {
		e.preventDefault();
		if (!username.trim()) return;
		setBusy(true);
		try {
			await login(username.trim(), password || undefined);
			navigate('/projects');
		} catch (err) {
			toast.error(err instanceof Error ? err.message : '登录失败');
		} finally {
			setBusy(false);
		}
	};

	return (
		<div className="flex h-screen items-center justify-center bg-muted/40">
			<Card className="w-full max-w-sm">
				<CardHeader>
					<CardTitle>软件造价评估平台</CardTitle>
					<CardDescription>
						输入用户名登录；开发环境未设口令的账号可直接登录。
					</CardDescription>
				</CardHeader>
				<CardContent>
					<form onSubmit={submit} className="space-y-4">
						<div className="space-y-2">
							<Label htmlFor="username">用户名</Label>
							<Input
								id="username"
								value={username}
								onChange={(e) => setUsername(e.target.value)}
								placeholder="例如 wenbo"
								autoFocus
							/>
						</div>
						<div className="space-y-2">
							<Label htmlFor="password">
								口令 <span className="text-muted-foreground">(无口令账号可留空)</span>
							</Label>
							<Input
								id="password"
								type="password"
								value={password}
								onChange={(e) => setPassword(e.target.value)}
							/>
						</div>
						<Button type="submit" className="w-full" disabled={busy || !username.trim()}>
							{busy && <Loader2 className="animate-spin" />}
							登录
						</Button>
					</form>
				</CardContent>
			</Card>
		</div>
	);
}
