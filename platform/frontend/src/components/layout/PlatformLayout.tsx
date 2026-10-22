import { useQuery } from '@tanstack/react-query';
import { FolderKanban } from 'lucide-react';
import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom';

import { api } from '@/api/platform';
import { useAuth } from '@/auth';
import { Button } from '@/components/ui/button';

const navCls = ({ isActive }: { isActive: boolean }) =>
	`rounded-md px-3 py-1.5 text-sm transition-colors ${
		isActive
			? 'bg-muted font-medium text-foreground'
			: 'text-muted-foreground hover:text-foreground'
	}`;

/**
 * Minimal chrome for the platform app: a top bar with brand + role-aware
 * nav + user + logout, and the routed page below. The AgentScope app's
 * icon-rail AppLayout is not reused — this app's navigation is
 * project-centric.
 */
export function PlatformLayout() {
	const { user, logout } = useAuth();
	const navigate = useNavigate();
	// 审批中心角标：与各页共享同一个 queryKey，轮询与失效全局生效
	const approvals = useQuery({
		queryKey: ['approvals'],
		queryFn: api.pendingApprovals,
		refetchInterval: 5000,
	});
	const pending = approvals.data?.length ?? 0;

	return (
		<div className="flex h-screen flex-col bg-background text-foreground">
			<header className="flex h-14 shrink-0 items-center justify-between border-b px-4">
				<div className="flex items-center gap-6">
					<Link to="/projects" className="flex items-center gap-2 font-semibold">
						<FolderKanban className="size-5" />
						软件全生命周期管控平台
					</Link>
					{/* 负责人视角（我的项目）/ 审批人视角（审批中心）入口并排 */}
					<nav className="flex items-center gap-1">
						<NavLink to="/projects" className={navCls}>
							我的项目
						</NavLink>
						<NavLink to="/approvals" className={navCls}>
							审批中心
							{pending > 0 && (
								<span className="ml-1.5 inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-destructive px-1 text-xs font-medium text-destructive-foreground">
									{pending}
								</span>
							)}
						</NavLink>
					</nav>
				</div>
				<div className="flex items-center gap-3 text-sm text-muted-foreground">
					{user && <span>{user.username}</span>}
					<Button
						variant="ghost"
						size="sm"
						onClick={() => {
							logout();
							navigate('/login');
						}}
					>
						退出
					</Button>
				</div>
			</header>
			<main className="min-h-0 flex-1 overflow-hidden">
				<Outlet />
			</main>
		</div>
	);
}
