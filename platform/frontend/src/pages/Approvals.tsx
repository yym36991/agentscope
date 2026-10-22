import { useQuery } from '@tanstack/react-query';
import { ClipboardCheck } from 'lucide-react';
import { useState } from 'react';

import { api, STAGE_LABELS, type ApprovalOut } from '@/api/platform';
import { ApprovalDecideDialog } from '@/components/approval/ApprovalDecideDialog';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';

/** 审批中心：审批人视角的收件箱 —— 只看待审任务与产物，不进项目流程。 */
export function ApprovalsPage() {
	const approvals = useQuery({
		queryKey: ['approvals'],
		queryFn: api.pendingApprovals,
		refetchInterval: 5000,
	});
	const [decideTask, setDecideTask] = useState<ApprovalOut | null>(null);

	return (
		<div className="h-full overflow-auto p-6">
			<div className="mx-auto max-w-4xl space-y-4">
				<h1 className="text-lg font-semibold">审批中心</h1>
				<p className="text-sm text-muted-foreground">
					分配给我的待审任务。主操作是审产物后通过/退回；需要溯源过程时，
					可在审批详情中查看负责人的完整对话（只读）。
				</p>

				{approvals.isLoading && <p className="text-sm text-muted-foreground">加载中…</p>}
				{approvals.data?.length === 0 && (
					<Card>
						<CardContent className="flex flex-col items-center gap-2 py-10 text-center text-sm text-muted-foreground">
							<ClipboardCheck className="size-6" />
							没有待审批任务。
						</CardContent>
					</Card>
				)}

				<div className="grid gap-3">
					{approvals.data?.map((a) => (
						<Card key={a.id} className="py-4">
							<CardContent className="flex items-center justify-between px-4 py-0">
								<div>
									<div className="font-medium">{a.project_name}</div>
									<div className="mt-1 text-xs text-muted-foreground">
										{STAGE_LABELS[a.stage] ?? a.stage} · 第 {a.run_round} 轮 ·
										运行 #{a.stage_run_id} 待审产物
									</div>
								</div>
								<Button size="sm" variant="outline" onClick={() => setDecideTask(a)}>
									审批
								</Button>
							</CardContent>
						</Card>
					))}
				</div>
			</div>

			<ApprovalDecideDialog
				task={decideTask}
				onOpenChange={(open) => !open && setDecideTask(null)}
			/>
		</div>
	);
}
