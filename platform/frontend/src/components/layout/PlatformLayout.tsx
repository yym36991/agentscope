import { FolderKanban } from 'lucide-react';
import { Link, Outlet, useNavigate } from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { useAuth } from '@/auth';

/**
 * Minimal chrome for the platform app: a top bar with brand + user +
 * logout, and the routed page below. The AgentScope app's icon-rail
 * AppLayout is not reused — this app's navigation is project-centric.
 */
export function PlatformLayout() {
	const { user, logout } = useAuth();
	const navigate = useNavigate();

	return (
		<div className="flex h-screen flex-col bg-background text-foreground">
			<header className="flex h-14 shrink-0 items-center justify-between border-b px-4">
				<div className="flex items-center gap-2">
					<Link to="/projects" className="flex items-center gap-2 font-semibold">
						<FolderKanban className="size-5" />
						软件造价评估平台
					</Link>
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
