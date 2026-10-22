import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
	ArrowLeft,
	CheckCircle2,
	Circle,
	CircleDotDashed,
	Loader2,
	MessagesSquare,
	Play,
	UserPlus,
	X,
} from 'lucide-react';
import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { toast } from 'sonner';

import { api, ROLE_LABELS, STAGE_LABELS, STAGE_ORDER, type ApprovalOut } from '@/api/platform';
import { useAuth } from '@/auth';
import { ApprovalDecideDialog } from '@/components/approval/ApprovalDecideDialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from '@/components/ui/select';

const RUN_STATUS: Record<string, string> = {
	in_progress: '进行中',
	under_review: '待审批',
	approved: '已通过',
	returned: '已退回',
};

/** 视图 A 核心：项目生命周期（阶段时间线 + 运行 + 成员 + 审批）。 */
export function ProjectDetailPage() {
	const { projectId } = useParams();
	const pid = Number(projectId);
	const navigate = useNavigate();
	const queryClient = useQueryClient();
	const { user } = useAuth();

	const project = useQuery({ queryKey: ['project', pid], queryFn: () => api.getProject(pid) });
	const runs = useQuery({ queryKey: ['runs', pid], queryFn: () => api.listStageRuns(pid), refetchInterval: 5000 });
	const approvals = useQuery({
		queryKey: ['approvals'],
		queryFn: api.pendingApprovals,
		refetchInterval: 5000,
	});
	const projectApprovals = (approvals.data ?? []).filter((a) => a.project_id === pid);

	const [starting, setStarting] = useState<string | null>(null);
	const [decideTask, setDecideTask] = useState<ApprovalOut | null>(null);

	// 成员管理：只有负责人能增删，其余成员只读
	const members = useQuery({ queryKey: ['members', pid], queryFn: () => api.listMembers(pid) });
	const [addingMember, setAddingMember] = useState(false);
	const [memberName, setMemberName] = useState('');
	const [memberRole, setMemberRole] = useState('approver');

	const addMember = useMutation({
		mutationFn: () => api.addMember(pid, memberName.trim(), memberRole),
		onSuccess: (m) => {
			toast.success(`已添加 ${m.display_name || m.username}（${ROLE_LABELS[m.role] ?? m.role}）`);
			setMemberName('');
			setAddingMember(false);
			queryClient.invalidateQueries({ queryKey: ['members', pid] });
		},
		onError: (err) => toast.error(err.message),
	});
	const removeMember = useMutation({
		mutationFn: (userId: number) => api.removeMember(pid, userId),
		onSuccess: () => queryClient.invalidateQueries({ queryKey: ['members', pid] }),
		onError: (err) => toast.error(err.message),
	});

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
			else toast.success(`「${STAGE_LABELS[stage]}」阶段已开启，发送首条消息后智能体开工`);
			invalidate();
			navigate(`/projects/${pid}/workbench/${run.id}`);
		} catch (err) {
			toast.error(err instanceof Error ? err.message : '启动失败');
		} finally {
			setStarting(null);
		}
	};

	if (project.isLoading) return <p className="p-6 text-sm text-muted-foreground">加载中…</p>;
	if (project.isError || !project.data)
		return <p className="p-6 text-sm text-destructive">项目不存在</p>;
	const p = project.data;
	const isOwner = p.owner_user_id === user?.id;

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

	// 只读回看：某阶段最新一轮已通过的 run（时间线「查看」入口的跳转目标）
	const latestApprovedRun = (stage: string) =>
		(runs.data ?? [])
			.filter((r) => r.stage === stage && r.status === 'approved')
			.sort((a, b) => b.round - a.round)[0];

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
										{state === 'approved' && latestApprovedRun(stage) && (
											<Button size="sm" variant="ghost" className="h-6 px-2 text-xs" asChild>
												<Link
													to={`/projects/${pid}/workbench/${latestApprovedRun(stage)!.id}`}
													title="只读回看本阶段已通过轮次的对话与产物"
												>
													查看
												</Link>
											</Button>
										)}
										{state === 'in_progress' && <span className="text-blue-600">进行中</span>}
										{state === 'under_review' && <span className="text-amber-600">待审批</span>}
										{state === 'available' && (
											<Button
												size="sm"
												variant="outline"
												disabled={starting === stage}
												title="开启本阶段：只创建运行，进入工作台补充说明或材料后再开始与智能体协作"
												onClick={() => startStage(stage)}
											>
												{starting === stage ? <Loader2 className="animate-spin" /> : <Play />}
												开启
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
									<Button size="sm" variant="ghost" asChild>
										<Link
											to={`/projects/${pid}/workbench/${r.id}`}
											title={r.status === 'in_progress' ? undefined : '只读回看当时的完整对话与产物'}
										>
											{r.status === 'in_progress' ? '工作台' : '查看'}
										</Link>
									</Button>
								</div>
							</div>
						))}
					</CardContent>
				</Card>

				{/* 成员管理：负责人增删成员；添加「审批人」后，后续提交的
				    产物会推送到对方的审批中心 */}
				<Card>
					<CardHeader className="flex-row items-center justify-between">
						<div>
							<CardTitle className="text-base">项目成员</CardTitle>
							<CardDescription>
								添加「审批人」角色的成员后，新提交的产物将进入对方的「审批中心」；
								已在途的审批任务仍归原审批人。
							</CardDescription>
						</div>
						{isOwner && (
							<Button size="sm" variant="outline" onClick={() => setAddingMember(!addingMember)}>
								<UserPlus /> 添加成员
							</Button>
						)}
					</CardHeader>
					<CardContent className="space-y-2">
						{addingMember && isOwner && (
							<form
								className="flex items-end gap-2 rounded-lg border p-3"
								onSubmit={(e) => {
									e.preventDefault();
									addMember.mutate();
								}}
							>
								<div className="flex-1 space-y-1">
									<Label htmlFor="member-name">用户名</Label>
									<Input
										id="member-name"
										value={memberName}
										onChange={(e) => setMemberName(e.target.value)}
										placeholder="对方注册的用户名，如 approver1"
									/>
								</div>
								<div className="space-y-1">
									<Label>角色</Label>
									<Select value={memberRole} onValueChange={setMemberRole}>
										<SelectTrigger className="w-32">
											<SelectValue />
										</SelectTrigger>
										<SelectContent>
											<SelectItem value="approver">审批人</SelectItem>
											<SelectItem value="manager">项目经理</SelectItem>
											<SelectItem value="member">成员</SelectItem>
											<SelectItem value="observer">观察者</SelectItem>
										</SelectContent>
									</Select>
								</div>
								<Button type="submit" size="sm" disabled={!memberName.trim() || addMember.isPending}>
									{addMember.isPending && <Loader2 className="animate-spin" />}
									添加
								</Button>
							</form>
						)}
						{(members.data ?? []).map((m) => (
							<div
								key={m.id}
								className="flex items-center justify-between rounded-lg border px-3 py-2 text-sm"
							>
								<div className="flex items-center gap-3">
									<span className="font-medium">{m.display_name || m.username}</span>
									<span className="text-xs text-muted-foreground">@{m.username}</span>
								</div>
								<div className="flex items-center gap-3">
									<Badge variant={m.role === 'approver' ? 'default' : 'secondary'}>
										{ROLE_LABELS[m.role] ?? m.role}
									</Badge>
									{isOwner && m.user_id !== p.owner_user_id && (
										<Button
											size="sm"
											variant="ghost"
											className="h-6 w-6 px-0 text-destructive"
											title="移除成员"
											disabled={removeMember.isPending}
											onClick={() => removeMember.mutate(m.user_id)}
										>
											<X />
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
							{projectApprovals.map((a) => (
								<div
									key={a.id}
									className="flex items-center justify-between rounded-lg border px-3 py-2 text-sm"
								>
									<span>
										{STAGE_LABELS[a.stage] ?? a.stage} · 第 {a.run_round} 轮 · 运行 #
										{a.stage_run_id} 待审产物
									</span>
									<div className="flex gap-2">
										<Button size="sm" variant="outline" onClick={() => setDecideTask(a)}>
											审批
										</Button>
									</div>
								</div>
							))}
						</CardContent>
					</Card>
				)}
			</div>

			{/* 审批对话框：预览待审产物后通过/退回（与审批中心共用） */}
			<ApprovalDecideDialog
				task={decideTask}
				onOpenChange={(open) => !open && setDecideTask(null)}
				onDecided={invalidate}
			/>
		</div>
	);
}
