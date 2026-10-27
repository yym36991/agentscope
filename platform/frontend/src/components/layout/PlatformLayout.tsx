import { useQuery } from '@tanstack/react-query';
import {
	Boxes,
	ClipboardCheck,
	FolderKanban,
	LogOut,
	Store,
	Wand2,
} from 'lucide-react';
import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom';

import { api } from '@/api/platform';
import { useAuth } from '@/auth';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

const itemCls = ({ isActive }: { isActive: boolean }) =>
	cn(
		'flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors',
		isActive
			? 'bg-primary/12 font-medium text-primary'
			: 'text-muted-foreground hover:bg-primary/5 hover:text-foreground',
	);

/**
 * Platform chrome: a left activity sidebar (Trae / AgentScope icon-rail
 * mental model) — workbench entries on top, the resource center below.
 * Knowledge bases, MCP and skill hubs are platform-level shared
 * resources (group-authorized / sys:runtime-owned), so they live in the
 * sidebar next to each other rather than inside either of the two views.
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
		<div className="flex h-screen bg-background text-foreground">
			<aside className="flex w-56 shrink-0 flex-col gap-1 border-r bg-sidebar p-3">
				<Link to="/projects" className="mb-3 flex items-center gap-2 px-2 py-1.5 font-semibold">
					<span className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
						<Store className="size-4.5" />
					</span>
					<span className="text-sm leading-tight">软件全生命周期<br />管控平台</span>
				</Link>

				<p className="px-3 pb-1 pt-2 text-[11px] font-medium tracking-wide text-muted-foreground/70">
					工作台
				</p>
				<NavLink to="/projects" className={itemCls}>
					<FolderKanban className="size-4" /> 我的项目
				</NavLink>
				<NavLink to="/approvals" className={itemCls}>
					<ClipboardCheck className="size-4" /> 审批中心
					{pending > 0 && (
						<span className="ml-auto inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-destructive px-1 text-xs font-medium text-destructive-foreground">
							{pending}
						</span>
					)}
				</NavLink>

				<p className="px-3 pb-1 pt-4 text-[11px] font-medium tracking-wide text-muted-foreground/70">
					资源中心
				</p>
				<NavLink to="/resources/kb" className={itemCls}>
					<Boxes className="size-4" /> 知识库
				</NavLink>
				<NavLink to="/resources/mcp" className={itemCls}>
					<span className="text-base leading-none">🔌</span> MCP Hub
				</NavLink>
				<NavLink to="/resources/skills" className={itemCls}>
					<Wand2 className="size-4" /> 技能 Hub
				</NavLink>
				<NavLink to="/resources/price" className={itemCls}>
					<span className="text-base leading-none">💰</span> 价格基准
				</NavLink>

				<div className="mt-auto rounded-lg border bg-card px-3 py-2.5">
					<div className="truncate text-sm font-medium">
						{user?.username}
						{user?.role === 'admin' && (
							<span className="ml-1.5 rounded bg-primary/15 px-1 py-px text-[10px] text-primary">
								管理员
							</span>
						)}
					</div>
					<div className="truncate text-xs text-muted-foreground">
						{(user?.groups ?? []).join('、') || '未加入任何组'}
					</div>
					<Button
						variant="ghost"
						size="sm"
						className="mt-1.5 w-full justify-start px-2 text-muted-foreground"
						onClick={() => {
							logout();
							navigate('/login');
						}}
					>
						<LogOut className="size-4" /> 退出登录
					</Button>
				</div>
			</aside>
			<main className="min-h-0 min-w-0 flex-1 overflow-hidden">
				<Outlet />
			</main>
		</div>
	);
}
