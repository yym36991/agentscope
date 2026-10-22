import { QueryClientProvider } from '@tanstack/react-query';
import { Navigate, RouterProvider, createBrowserRouter } from 'react-router-dom';
import { Toaster } from 'sonner';

import { RouteError } from '@/components/error/RouteError';
import { PlatformLayout } from '@/components/layout/PlatformLayout';
import { queryClient } from '@/lib/query-client';
import { AuthProvider, useAuth } from '@/auth';
import { ApprovalsPage } from '@/pages/Approvals';
import { LoginPage } from '@/pages/Login';
import { ProjectDetailPage } from '@/pages/ProjectDetail';
import { ProjectsPage } from '@/pages/Projects';
import { WorkbenchPage } from '@/pages/Workbench';

/** Gate for authenticated routes: waits for the auth probe, then decides. */
function RequireAuth({ children }: { children: React.ReactNode }) {
	const { user, ready } = useAuth();
	if (!ready) return <p className="p-6 text-sm text-muted-foreground">加载中…</p>;
	if (!user) return <Navigate to="/login" replace />;
	return <>{children}</>;
}

const router = createBrowserRouter([
	{ path: '/login', element: <LoginPage />, errorElement: <RouteError /> },
	{
		path: '/',
		element: (
			<RequireAuth>
				<PlatformLayout />
			</RequireAuth>
		),
		errorElement: <RouteError />,
		children: [
			{ index: true, element: <Navigate to="/projects" replace /> },
			{ path: '/projects', element: <ProjectsPage /> },
			{ path: '/approvals', element: <ApprovalsPage /> },
			{
				path: '/projects/:projectId',
				errorElement: <RouteError />,
				children: [
					{ index: true, element: <ProjectDetailPage /> },
					{ path: 'workbench/:runId', element: <WorkbenchPage /> },
				],
			},
		],
	},
]);

function App() {
	return (
		<QueryClientProvider client={queryClient}>
			<AuthProvider>
				<RouterProvider router={router} />
				<Toaster richColors position="top-right" />
			</AuthProvider>
		</QueryClientProvider>
	);
}

export default App;
