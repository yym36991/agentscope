import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
	ArrowLeft,
	CheckCircle2,
	Circle,
	CircleDotDashed,
	Loader2,
	MessagesSquare,
	Play,
} from 'lucide-react';
import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { toast } from 'sonner';

import { api, STAGE_LABELS, STAGE_ORDER } from '@/api/platform';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
	Dialog,
	DialogClose,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';

const RUN_STATUS: Record<string, string> = {
	in_progress: '进行中',
	under_review: '待审批',
	approved: '已通过',
	returned: '已退回',
};

/** 视图 A 核心：项目生命周期（阶段时间线 + 运行 + 审批）。 */
export function ProjectDetailPage() {
	const { projectId } = useParams();
	const pid = Number(projectId);
	const navigate = useNavigate();
	const queryClient = useQueryClient();

	const project = useQuery({ queryKey: ['project', pid], queryFn: () => api.getProject(pid) });
	const runs = useQuery({ queryKey: ['runs', pid], queryFn: () => api.listStageRuns(pid), refetchInterval: 5000 });
	const approvals = useQuery({
		queryKey: ['approvals'],
		queryFn: api.pendingApprovals,
		refetchInterval: 5000,
	});
	const projectApprovals = (approvals.data ?? []).filter((a) => a.project_id === pid);

	const [starting, setStarting] = useState<string | null>(null);
	const [decideTask, setDecideTask] = useState<number | null>(null);
	const [comment, setComment] = useState('');

	const invalidate = () => {
		queryClient.invalidateQueries({ queryKey: ['project', pid] });
		queryClient.invalidateQueries({ queryKey: ['runs', pid] });
		queryClient.invalidateQueries({ queryKey: ['approvals'] });
	};

	const startStage = async (stage: string) => {
		setStarting(stage);
		try {
			const run = await api.startStage(pid, stage);
			if (run.warning) toast.warning(run.warning);
			else toast.success(`「${STAGE_LABELS[stage]}」阶段已启动`);
			invalidate();
			navigate(`/projects/${pid}/workbench/${run.id}`);
		} catch (err) {
			toast.error(err instanceof Error ? err.message : '启动失败');
		} finally {
			setStarting(null);
		}
	};

	const decide = useMutation({
		mutationFn: ({ task, action, text }: { task: number; action: 'approve' | 'return'; text?: string }) =>
			api.decide(task, action, text),
		onSuccess: (res, vars) => {
			toast.success(
				vars.action === 'approve'
					? `已通过，项目推进到「${STAGE_LABELS[res.project_stage] ?? res.project_stage}」`
					: '已退回，发起人可重新开启该阶段',
			);
			setDecideTask(null);
			setComment('');
			invalidate();
		},
		onError: (err) => toast.error(err.message),
	});

	if (project.isLoading) return <p className="p-6 text-sm text-muted-foreground">加载中…</p>;
	if (project.isError || !project.data)
		return <p className="p-6 text-sm text-destructive">项目不存在</p>;
	const p = project.data;

	const stageState = (stage: string) => {
		const stageRuns = (runs.data ?? []).filter((r) => r.stage === stage);
		if (stageRuns.some((r) => r.status === 'approved')) return 'approved';
		const active = stageRuns.find((r) => r.status === 'in_progress' || r.status === 'under_review');
		if (active) return active.status === 'in_progress' ? 'in_progress' : 'under_review';
		const isNext =
			p.current_stage === 'none' ? stage === 'requirement' : stage === p.current_stage;
		return isNext && p.status !== 'accepted' ? 'available' : 'locked';
	};

	const activeRun = (runs.data ?? []).find(
		(r) => r.stage === p.current_stage && r.status === 'in_progress',
	);

	return (
		<div className="h-full overflow-auto p-6">
			<div className="mx-auto max-w-4xl space-y-5">
				<div className="flex items-center gap-3">
					<Button variant="ghost" size="icon" asChild>
						<Link to="/projects">
							<ArrowLeft />
						</Link>
					</Button>
					<h1 className="text-lg font-semibold">{p.name}</h1>
					<Badge variant={p.status === 'active' ? 'default' : 'secondary'}>{p.status}</Badge>
				</div>

				{/* 阶段时间线 */}
				<Card>
					<CardHeader>
						<CardTitle className="text-base">项目生命周期</CardTitle>
					</CardHeader>
					<CardContent>
						<div className="grid grid-cols-6 gap-2">
							{STAGE_ORDER.map((stage) => {
								const state = stageState(stage);
								return (
									<div
										key={stage}
										className="flex flex-col items-center gap-2 rounded-lg border p-3 text-center text-xs"
									>
										{state === 'approved' ? (
											<CheckCircle2 className="size-5 text-green-600" />
										) : state === 'in_progress' ? (
											<CircleDotDashed className="size-5 animate-pulse text-blue-600" />
										) : state === 'under_review' ? (
											<CircleDotDashed className="size-5 text-amber-600" />
										) : (
											<Circle className="size-5 text-muted-foreground" />
										)}
										<span className="font-medium">{STAGE_LABELS[stage]}</span>
										{state === 'approved' && <span className="text-green-600">已通过</span>}
										{state === 'in_progress' && <span className="text-blue-600">进行中</span>}
										{state === 'under_review' && <span className="text-amber-600">待审批</span>}
										{state === 'available' && (
											<Button size="sm" variant="outline" disabled={starting === stage} onClick={() => startStage(stage)}>
												{starting === stage ? <Loader2 className="animate-spin" /> : <Play />}
												启动
											</Button>
										)}
										{state === 'locked' && <span className="text-muted-foreground">—</span>}
									</div>
								);
							})}
						</div>
					</CardContent>
				</Card>

				{/* 运行历史 */}
				<Card>
					<CardHeader className="flex-row items-center justify-between">
						<CardTitle className="text-base">阶段运行</CardTitle>
						{activeRun && (
							<Button size="sm" asChild>
								<Link to={`/projects/${pid}/workbench/${activeRun.id}`}>
									<MessagesSquare />
									进入 Agent 对话
								</Link>
							</Button>
						)}
					</CardHeader>
					<CardContent className="space-y-2">
						{(runs.data ?? []).length === 0 && (
							<p className="text-sm text-muted-foreground">还没有任何阶段运行。</p>
						)}
						{(runs.data ?? []).map((r) => (
							<div
								key={r.id}
								className="flex items-center justify-between rounded-lg border px-3 py-2 text-sm"
							>
								<div className="flex items-center gap-3">
									<span className="font-medium">{STAGE_LABELS[r.stage] ?? r.stage}</span>
									<span className="text-xs text-muted-foreground">第 {r.round} 轮</span>
								</div>
								<div className="flex items-center gap-3">
									<Badge variant={r.status === 'approved' ? 'default' : 'secondary'}>
										{RUN_STATUS[r.status] ?? r.status}
									</Badge>
									{r.status === 'in_progress' && (
										<Button size="sm" variant="ghost" asChild>
											<Link to={`/projects/${pid}/workbench/${r.id}`}>工作台</Link>
										</Button>
									)}
								</div>
							</div>
						))}
					</CardContent>
				</Card>

				{/* 审批 */}
				{projectApprovals.length > 0 && (
					<Card>
						<CardHeader>
							<CardTitle className="text-base">待我审批</CardTitle>
						</CardHeader>
						<CardContent className="space-y-2">
							{projectApprovals.map((a) => {
								const run = (runs.data ?? []).find((r) => r.id === a.stage_run_id);
								return (
									<div
										key={a.id}
										className="flex items-center justify-between rounded-lg border px-3 py-2 text-sm"
									>
										<span>
											{STAGE_LABELS[a.stage] ?? a.stage} · 运行 #{a.stage_run_id}
											{run && ` · 第 ${run.round} 轮`} 待审产物
										</span>
										<div className="flex gap-2">
											<Button size="sm" variant="outline" onClick={() => setDecideTask(a.id)}>
												审批
											</Button>
										</div>
									</div>
								);
							})}
						</CardContent>
					</Card>
				)}
			</div>

			{/* 审批对话框 */}
			<Dialog open={decideTask !== null} onOpenChange={(open) => !open && setDecideTask(null)}>
				<DialogContent>
					<DialogHeader>
						<DialogTitle>审批决定</DialogTitle>
						<DialogDescription>
							退回必须填写意见，发起人将看到意见并重新开启该阶段（轮次 +1）。
						</DialogDescription>
					</DialogHeader>
					<Textarea
						placeholder="审批意见（退回时必填）"
						value={comment}
						onChange={(e) => setComment(e.target.value)}
					/>
					<DialogFooter>
						<DialogClose asChild>
							<Button variant="outline">取消</Button>
						</DialogClose>
						<Button
							variant="destructive"
							disabled={decide.isPending || !comment.trim()}
							onClick={() => decideTask && decide.mutate({ task: decideTask, action: 'return', text: comment })}
						>
							{decide.isPending && decide.variables?.action === 'return' && <Loader2 className="animate-spin" />}
							退回
						</Button>
						<Button
							disabled={decide.isPending}
							onClick={() => decideTask && decide.mutate({ task: decideTask, action: 'approve', text: comment || undefined })}
						>
							{decide.isPending && decide.variables?.action === 'approve' && <Loader2 className="animate-spin" />}
							通过
						</Button>
					</DialogFooter>
				</DialogContent>
			</Dialog>
		</div>
	);
}
