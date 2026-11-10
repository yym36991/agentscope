import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
	ArrowLeft,
	Boxes,
	Loader2,
	MessagesSquare,
	Play,
	UserPlus,
	X,
} from 'lucide-react';
import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { toast } from 'sonner';

import {
	api,
	KB_TYPE_LABELS,
	ROLE_LABELS,
	STAGE_LABELS,
	STAGE_ORDER,
	type ApprovalOut,
} from '@/api/platform';
import { useAuth } from '@/auth';
import { ApprovalDecideDialog } from '@/components/approval/ApprovalDecideDialog';
import {
	StageTimeline,
	STAGE_STATE_TEXT,
	computeStageStates,
} from '@/components/platform/StageStepper';
import { StageGantt } from '@/components/platform/StageGantt';
import { TraceMatrix } from '@/components/platform/TraceMatrix';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from '@/components/ui/card';
import {
	Dialog,
	DialogClose,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from '@/components/ui/dialog';
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

/** 视图 A 核心：项目生命周期（时间线 + 选中阶段的运行 + 成员 + 审批 + 知识库绑定）。
 * 六阶段全流程只在页面顶部出现一次；项目列表与工作台左栏用迷你进度点。 */
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
	// 时间线选中阶段（必须在早退 return 之前：hooks 数量不能随加载状态变化）
	const [selectedStage, setSelectedStage] = useState<string | null>(null);

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
		onSuccess: ({ reassigned_tasks }) => {
			toast.success(`已移除成员${reassigned_tasks > 0 ? `，${reassigned_tasks} 条在途审批已改道给你` : ''}`);
			queryClient.invalidateQueries({ queryKey: ['members', pid] });
			queryClient.invalidateQueries({ queryKey: ['approvals'] });
		},
		onError: (err) => toast.error(err.message),
	});

	// 知识库绑定：负责人把组授权的库按阶段挂到项目（M3 §7.2）
	const kbLinks = useQuery({ queryKey: ['kb-links', pid], queryFn: () => api.listKbLinks(pid) });
	const kbs = useQuery({ queryKey: ['kbs'], queryFn: api.listKbs });
	const [linking, setLinking] = useState(false);
	const [linkKbId, setLinkKbId] = useState<number | null>(null);
	const [linkStage, setLinkStage] = useState<string>('all');
	const addLink = useMutation({
		mutationFn: () => api.addKbLink(pid, linkKbId!, linkStage === 'all' ? null : linkStage),
		onSuccess: (l) => {
			toast.success(`已绑定「${l.kb_name}」`);
			setLinking(false);
			setLinkKbId(null);
			setLinkStage('all');
			queryClient.invalidateQueries({ queryKey: ['kb-links', pid] });
		},
		onError: (err) => toast.error(err.message),
	});
	const removeLink = useMutation({
		mutationFn: (linkId: number) => api.removeKbLink(pid, linkId),
		onSuccess: () => {
			toast.success('已解除绑定');
			queryClient.invalidateQueries({ queryKey: ['kb-links', pid] });
		},
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

	const states = computeStageStates(p, runs.data ?? []);
	const activeRun = (runs.data ?? []).find(
		(r) => r.stage === p.current_stage && r.status === 'in_progress',
	);
	// 时间线默认聚焦：进行中的阶段，否则可开启的下一站，否则最近一个有运行的阶段。
	// 审批通过后 current_stage 已推进、上一阶段无活跃运行——此时聚焦下一站，
	// 「开启」按钮（只对聚焦的 available 阶段显示）才直接可见。
	const defaultStage =
		activeRun?.stage ??
		STAGE_ORDER.find((s) => states[s] === 'available') ??
		(runs.data ?? []).at(-1)?.stage ??
		'requirement';
	const focus = selectedStage ?? defaultStage;
	const focusRuns = (runs.data ?? [])
		.filter((r) => r.stage === focus)
		.sort((a, b) => b.round - a.round);

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

				{/* 阶段时间线 + 选中阶段的运行（完整流程全站只在这一处展开） */}
				<Card>
					<CardHeader className="flex-row items-center justify-between space-y-0">
						<div>
							<CardTitle className="text-base">项目生命周期</CardTitle>
							<CardDescription>
								点击阶段查看该阶段的各轮运行与产物；下一站在下方直接开启。
							</CardDescription>
						</div>
						{activeRun && (
							<Button size="sm" asChild>
								<Link to={`/projects/${pid}/workbench/${activeRun.id}`}>
									<MessagesSquare /> 进入 Agent 对话
								</Link>
							</Button>
						)}
					</CardHeader>
					<CardContent>
						<StageTimeline states={states} selected={focus} onSelect={setSelectedStage} />
						<div className="mt-3 flex items-center justify-between gap-2 rounded-lg border bg-muted/30 px-3 py-2">
							<span className="text-xs text-muted-foreground">
								{STAGE_LABELS[focus] ?? focus} · {STAGE_STATE_TEXT[states[focus] ?? 'locked']}
							</span>
							{states[focus] === 'available' && (
								<Button
									size="sm"
									disabled={starting === focus}
									title="开启本阶段：只创建运行，进入工作台补充说明或材料后再开始与智能体协作"
									onClick={() => startStage(focus)}
								>
									{starting === focus ? (
										<Loader2 className="size-4 animate-spin" />
									) : (
										<Play className="size-4" />
									)}
									开启「{STAGE_LABELS[focus]}」
								</Button>
							)}
						</div>
						<div className="mt-2 space-y-1.5">
							{focusRuns.length === 0 && (
								<p className="px-1 py-2 text-xs text-muted-foreground">
									该阶段还没有运行记录。
								</p>
							)}
							{focusRuns.map((r) => (
								<div
									key={r.id}
									className="flex items-center justify-between rounded-lg border px-3 py-2 text-sm"
								>
									<div className="flex items-center gap-3">
										<span className="font-medium">第 {r.round} 轮</span>
										<span className="text-xs text-muted-foreground">
											{new Date(r.created_at).toLocaleDateString()} 创建
										</span>
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
						</div>
					</CardContent>
				</Card>

				{/* 阶段甘特视图：每阶段一条横条（首轮创建 → 审批决定），标注轮次与退回 */}
				{(runs.data ?? []).length > 0 && (
					<Card>
						<CardHeader>
							<CardTitle className="text-base">进度甘特</CardTitle>
							<CardDescription>
								每阶段一条：从首轮运行创建画到审批决定，未收尾的画到当前时间（浅色）。
							</CardDescription>
						</CardHeader>
						<CardContent>
							<StageGantt runs={runs.data ?? []} />
						</CardContent>
					</Card>
				)}

				{/* 功能点与追溯矩阵（§7.3）：需求 → 功能点 → 用例 → 工时贯通 */}
				<Card>
					<CardHeader>
						<CardTitle className="text-base">功能点与追溯</CardTitle>
						<CardDescription>
							需求 → 功能点 → 测试用例 → 工时报价的贯通视图，取各阶段最新已批准轮次的结构化侧表。
						</CardDescription>
					</CardHeader>
					<CardContent>
						<TraceMatrix projectId={pid} />
					</CardContent>
				</Card>

				{/* 知识库绑定：按阶段挂载组授权的知识库，绑定后该阶段智能体自动检索 */}
				<Card>
					<CardHeader className="flex-row items-center justify-between space-y-0">
						<div>
							<CardTitle className="text-base">知识库绑定</CardTitle>
							<CardDescription>
								授权给本项目的知识库按阶段挂载，绑定后该阶段智能体会自动检索库内文档；
								「全部阶段」对所有阶段生效。可见范围 = 小组授权 ∩ 项目绑定。
							</CardDescription>
						</div>
						{isOwner && (
							<Button size="sm" variant="outline" onClick={() => setLinking(true)}>
								<Boxes /> 绑定知识库
							</Button>
						)}
					</CardHeader>
					<CardContent className="space-y-1.5">
						{(kbLinks.data ?? []).length === 0 && (
							<p className="text-xs text-muted-foreground">
								还没有绑定知识库{isOwner ? '，点右上角把行业规范 / 价格基准 / 案例库挂上来。' : '。'}
							</p>
						)}
						{(kbLinks.data ?? []).map((l) => (
							<div
								key={l.id}
								className="flex items-center justify-between rounded-lg border px-3 py-2 text-sm"
							>
								<div className="flex min-w-0 items-center gap-2">
									<Badge variant="secondary">{KB_TYPE_LABELS[l.kb_type] ?? l.kb_type}</Badge>
									<span className="truncate font-medium">{l.kb_name}</span>
									<span className="shrink-0 text-xs text-muted-foreground">
										{l.stage === null ? '全部阶段' : (STAGE_LABELS[l.stage] ?? l.stage)}
									</span>
								</div>
								{isOwner && (
									<Button
										size="sm"
										variant="ghost"
										className="h-6 w-6 px-0 text-destructive"
										title="解除绑定"
										disabled={removeLink.isPending}
										onClick={() => removeLink.mutate(l.id)}
									>
										<X />
									</Button>
								)}
							</div>
						))}
					</CardContent>
				</Card>

				{/* 成员管理：负责人增删成员；添加「审批人」后，后续提交的
				    产物会推送到对方的审批中心 */}
				<Card>
					<CardHeader className="flex-row items-center justify-between space-y-0">
						<div>
							<CardTitle className="text-base">项目成员</CardTitle>
							<CardDescription>
								添加「审批人」角色的成员后，新提交的产物将进入对方的「审批中心」；
								移除成员时，其名下在途待审任务自动改道回项目负责人。
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

			{/* 绑定知识库对话框：选库 + 生效阶段 */}
			<Dialog open={linking} onOpenChange={setLinking}>
				<DialogContent>
					<DialogHeader>
						<DialogTitle>绑定知识库</DialogTitle>
						<DialogDescription>
							只能绑定已授权给你所在小组的知识库（即「资源中心 · 知识库」里能看到的那批）。
						</DialogDescription>
					</DialogHeader>
					<div className="space-y-3">
						<div className="space-y-1.5">
							<Label>知识库</Label>
							<Select
								value={linkKbId?.toString() ?? ''}
								onValueChange={(v) => setLinkKbId(Number(v))}
							>
								<SelectTrigger>
									<SelectValue placeholder="选择知识库" />
								</SelectTrigger>
								<SelectContent>
									{(kbs.data ?? []).map((kb) => (
										<SelectItem key={kb.id} value={kb.id.toString()}>
											{kb.name}（{KB_TYPE_LABELS[kb.kb_type] ?? kb.kb_type}）
										</SelectItem>
									))}
								</SelectContent>
							</Select>
						</div>
						<div className="space-y-1.5">
							<Label>生效阶段</Label>
							<Select value={linkStage} onValueChange={setLinkStage}>
								<SelectTrigger>
									<SelectValue />
								</SelectTrigger>
								<SelectContent>
									<SelectItem value="all">全部阶段</SelectItem>
									{STAGE_ORDER.map((s) => (
										<SelectItem key={s} value={s}>
											{STAGE_LABELS[s]}
										</SelectItem>
									))}
								</SelectContent>
							</Select>
						</div>
					</div>
					<DialogFooter>
						<DialogClose asChild>
							<Button variant="outline">取消</Button>
						</DialogClose>
						<Button disabled={!linkKbId || addLink.isPending} onClick={() => addLink.mutate()}>
							{addLink.isPending && <Loader2 className="size-4 animate-spin" />} 绑定
						</Button>
					</DialogFooter>
				</DialogContent>
			</Dialog>
		</div>
	);
}
