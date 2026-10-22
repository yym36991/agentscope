import { Loader2 } from 'lucide-react';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

import { api } from '@/api/platform';
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

/** 登录 + 自助注册（D5：注册即入 default 组，口令可留空为开发引导态）。 */
export function LoginPage() {
	const { login } = useAuth();
	const navigate = useNavigate();
	const [mode, setMode] = useState<'login' | 'register'>('login');
	const [username, setUsername] = useState('');
	const [displayName, setDisplayName] = useState('');
	const [password, setPassword] = useState('');
	const [busy, setBusy] = useState(false);

	const submit = async (e: React.FormEvent) => {
		e.preventDefault();
		if (!username.trim()) return;
		setBusy(true);
		try {
			if (mode === 'register') {
				await api.register(
					username.trim(),
					password || undefined,
					displayName.trim() || undefined,
				);
				toast.success(`账号 ${username.trim()} 注册成功`);
			}
			// 注册成功后直接登录拿 JWT（无口令账号按用户名登录）
			await login(username.trim(), password || undefined);
			navigate('/projects');
		} catch (err) {
			toast.error(err instanceof Error ? err.message : '操作失败');
		} finally {
			setBusy(false);
		}
	};

	return (
		<div className="flex h-screen items-center justify-center bg-muted/40">
			<Card className="w-full max-w-sm">
				<CardHeader>
					<CardTitle>软件全生命周期管控平台</CardTitle>
					<CardDescription>
						{mode === 'login'
							? '输入用户名登录；开发环境未设口令的账号可直接登录。'
							: '自助注册（入默认组）；口令可留空（开发引导态，仅限内网）。'}
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
								placeholder="字母、数字、_ . -"
								autoFocus
							/>
						</div>
						{mode === 'register' && (
							<div className="space-y-2">
								<Label htmlFor="display-name">
									显示名称 <span className="text-muted-foreground">(可选)</span>
								</Label>
								<Input
									id="display-name"
									value={displayName}
									onChange={(e) => setDisplayName(e.target.value)}
									placeholder="例如：审批人-王工"
								/>
							</div>
						)}
						<div className="space-y-2">
							<Label htmlFor="password">
								口令{' '}
								<span className="text-muted-foreground">
									(至少 8 位；{mode === 'login' ? '无口令账号可留空' : '可留空'})
								</span>
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
							{mode === 'login' ? '登录' : '注册并登录'}
						</Button>
						<p className="text-center text-sm text-muted-foreground">
							{mode === 'login' ? (
								<>
									没有账号？
									<Button
										variant="link"
										size="sm"
										className="h-auto p-0"
										onClick={() => setMode('register')}
									>
										注册一个
									</Button>
								</>
							) : (
								<>
									已有账号？
									<Button
										variant="link"
										size="sm"
										className="h-auto p-0"
										onClick={() => setMode('login')}
									>
										直接登录
									</Button>
								</>
							)}
						</p>
					</form>
				</CardContent>
			</Card>
		</div>
	);
}
