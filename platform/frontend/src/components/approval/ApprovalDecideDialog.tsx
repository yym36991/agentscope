import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Loader2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';

import {
	api,
	STAGE_LABELS,
	type ApprovalOut,
	type ArtifactOut,
} from '@/api/platform';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
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

/**
 * 审批决定对话框（项目详情与审批中心共用）：主操作是审产物——预览
 * 该运行最新版本的产物内容，再看意见下结论；「查看完整对话」只是
 * 次级溯源入口，跳到该运行的只读工作台，不参与主流程。
 */
export function ApprovalDecideDialog({
	task,
	onOpenChange,
	onDecided,
}: {
	task: ApprovalOut | null;
	onOpenChange: (open: boolean) => void;
	onDecided?: () => void;
}) {
	const queryClient = useQueryClient();
	const [comment, setComment] = useState('');

	// 待审产物：under_review 运行必然提交过产物，空列表只是兜底
	const artifacts = useQuery({
		queryKey: ['run-artifacts', task?.stage_run_id],
		queryFn: () => api.listRunArtifacts(task!.stage_run_id),
		enabled: task !== null,
	});
	const latest = (artifacts.data ?? []).reduce<ArtifactOut | null>(
		(best, a) => (best === null || a.version_no > best.version_no ? a : best),
		null,
	);
	const content = useQuery({
		queryKey: ['run-artifact-content', task?.stage_run_id, latest?.id],
		queryFn: () => api.getRunArtifact(task!.stage_run_id, latest!.id),
		enabled: latest !== null,
	});

	const decide = useMutation({
		mutationFn: ({ action, text }: { action: 'approve' | 'return'; text?: string }) =>
			api.decide(task!.id, action, text),
		onSuccess: (res, vars) => {
			toast.success(
				vars.action === 'approve'
					? res.project_status === 'accepted'
						? '已通过，项目验收完成'
						: `已通过，「${STAGE_LABELS[res.project_stage] ?? res.project_stage}」阶段可开启`
					: '已退回，发起人可重新开启该阶段',
			);
			setComment('');
			onOpenChange(false);
			queryClient.invalidateQueries({ queryKey: ['approvals'] });
			onDecided?.();
		},
		onError: (err) => toast.error(err.message),
	});

	// 换一个任务打开时清空上一次的意见
	useEffect(() => {
		setComment('');
	}, [task?.id]);

	return (
		<Dialog open={task !== null} onOpenChange={onOpenChange}>
			<DialogContent className="sm:max-w-2xl">
				<DialogHeader>
					<DialogTitle>
						审批：{task ? `${task.project_name} · ${STAGE_LABELS[task.stage] ?? task.stage}` : ''}
					</DialogTitle>
					<DialogDescription>
						{task && `第 ${task.run_round} 轮 · 运行 #${task.stage_run_id}。`}
						退回必须填写意见，发起人将看到意见并重新开启该阶段（轮次 +1）。
					</DialogDescription>
				</DialogHeader>

				{/* 待审产物预览：先看东西，再下结论 */}
				<div className="space-y-2">
					<div className="flex items-center justify-between">
						<span className="text-sm font-medium">{latest ? latest.title : '待审产物'}</span>
						{latest && <Badge variant="secondary">{latest.format}</Badge>}
					</div>
					{artifacts.isLoading || content.isLoading ? (
						<p className="flex items-center gap-2 text-sm text-muted-foreground">
							<Loader2 className="size-4 animate-spin" /> 正在加载产物…
						</p>
					) : latest && content.data ? (
						<pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-md bg-muted/50 p-3 font-mono text-xs leading-relaxed">
							{content.data.content}
						</pre>
					) : (
						<p className="text-sm text-muted-foreground">没有可预览的产物版本。</p>
					)}
					{task && (
						<Button variant="link" size="sm" className="h-auto p-0 text-xs" asChild>
							<Link
								to={`/projects/${task.project_id}/workbench/${task.stage_run_id}`}
								title="跳到该运行的只读工作台，回看负责人与智能体的完整协作过程"
								onClick={() => onOpenChange(false)}
							>
								查看完整对话（只读）
							</Link>
						</Button>
					)}
				</div>

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
						onClick={() => decide.mutate({ action: 'return', text: comment })}
					>
						{decide.isPending && decide.variables?.action === 'return' && (
							<Loader2 className="animate-spin" />
						)}
						退回
					</Button>
					<Button
						disabled={decide.isPending}
						onClick={() => decide.mutate({ action: 'approve', text: comment || undefined })}
					>
						{decide.isPending && decide.variables?.action === 'approve' && (
							<Loader2 className="animate-spin" />
						)}
						通过
					</Button>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}
