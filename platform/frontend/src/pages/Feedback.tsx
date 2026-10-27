import { useQuery } from '@tanstack/react-query';
import { Check, MessageSquareText, Search, Undo2 } from 'lucide-react';
import { useState } from 'react';

import { api, STAGE_LABELS } from '@/api/platform';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from '@/components/ui/select';

const ACTION_LABELS = { approved: '通过', returned: '退回' } as const;

/** 管理视图 · 意见台账：全部项目的审批意见（通过 + 退回）跨项目聚合，
 *  可按项目 / 动作 / 关键词过滤 —— 交付复盘时找“当时为什么退回”就查这里。 */
export function FeedbackPage() {
	const [draft, setDraft] = useState({ project_id: '', action: '', q: '' });
	const [filters, setFilters] = useState({ project_id: '', action: '', q: '' });

	const projects = useQuery({ queryKey: ['projects'], queryFn: api.listProjects });
	const feedback = useQuery({
		queryKey: ['feedback', filters],
		queryFn: () =>
			api.listFeedback({
				project_id: filters.project_id ? Number(filters.project_id) : undefined,
				action: filters.action || undefined,
				q: filters.q || undefined,
			}),
	});

	return (
		<div className="h-full overflow-auto p-6">
			<div className="mx-auto max-w-5xl space-y-4">
				<div className="flex items-center gap-2.5">
					<span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
						<MessageSquareText className="size-4.5" />
					</span>
					<div>
						<h1 className="text-lg font-semibold">意见台账</h1>
						<p className="text-xs text-muted-foreground">
							全部项目的审批意见与退回意见，按时间倒序；管理员看全平台，成员看自己可见的项目。
						</p>
					</div>
				</div>

				<form
					className="flex flex-wrap items-center gap-2"
					onSubmit={(e) => {
						e.preventDefault();
						setFilters({
							project_id: draft.project_id,
							action: draft.action,
							q: draft.q.trim(),
						});
					}}
				>
					<Select
						value={draft.project_id}
						onValueChange={(v) => setDraft({ ...draft, project_id: v === 'all' ? '' : v })}
					>
						<SelectTrigger className="w-56">
							<SelectValue placeholder="全部项目" />
						</SelectTrigger>
						<SelectContent>
							<SelectItem value="all">全部项目</SelectItem>
							{(projects.data ?? []).map((p) => (
								<SelectItem key={p.id} value={String(p.id)}>
									{p.name}
								</SelectItem>
							))}
						</SelectContent>
					</Select>
					<Select
						value={draft.action}
						onValueChange={(v) => setDraft({ ...draft, action: v === 'all' ? '' : v })}
					>
						<SelectTrigger className="w-28">
							<SelectValue placeholder="全部动作" />
						</SelectTrigger>
						<SelectContent>
							<SelectItem value="all">全部动作</SelectItem>
							<SelectItem value="approved">通过</SelectItem>
							<SelectItem value="returned">退回</SelectItem>
						</SelectContent>
					</Select>
					<Input
						className="w-48"
						placeholder="意见关键字"
						value={draft.q}
						onChange={(e) => setDraft({ ...draft, q: e.target.value })}
					/>
					<Button type="submit" size="sm" variant="outline">
						<Search className="size-4" /> 筛选
					</Button>
					{(filters.project_id || filters.action || filters.q) && (
						<Button
							type="button"
							size="sm"
							variant="ghost"
							onClick={() => {
								setDraft({ project_id: '', action: '', q: '' });
								setFilters({ project_id: '', action: '', q: '' });
							}}
						>
							清除
						</Button>
					)}
				</form>

				<Card>
					<CardContent className="p-0">
						{feedback.isLoading ? (
							<p className="p-4 text-xs text-muted-foreground">加载中…</p>
						) : (feedback.data ?? []).length === 0 ? (
							<p className="p-6 text-center text-xs text-muted-foreground">
								还没有已决定并留下意见的审批。
							</p>
						) : (
							<table className="w-full text-sm">
								<thead>
									<tr className="border-b text-left text-xs text-muted-foreground">
										<th className="px-3 py-2 font-medium">时间</th>
										<th className="px-3 py-2 font-medium">项目</th>
										<th className="px-3 py-2 font-medium">环节</th>
										<th className="px-3 py-2 font-medium">动作</th>
										<th className="px-3 py-2 font-medium">意见</th>
										<th className="px-3 py-2 font-medium">审批人</th>
									</tr>
								</thead>
								<tbody>
									{feedback.data?.map((f) => (
										<tr key={f.id} className="border-b align-top last:border-0 hover:bg-row-hover">
											<td className="whitespace-nowrap px-3 py-2 text-xs tabular-nums text-muted-foreground">
												{new Date(f.decided_at).toLocaleString('zh-CN', {
													month: '2-digit',
													day: '2-digit',
													hour: '2-digit',
													minute: '2-digit',
												})}
											</td>
											<td className="max-w-40 px-3 py-2">
												<span className="block truncate" title={f.project_name ?? ''}>
													{f.project_name ?? `项目 #${f.project_id}`}
												</span>
											</td>
											<td className="whitespace-nowrap px-3 py-2 text-xs text-muted-foreground">
												{f.kind === 'stage'
													? `${STAGE_LABELS[f.stage ?? ''] ?? f.stage} · 第 ${f.run_round} 轮`
													: '知识沉淀审阅'}
											</td>
											<td className="whitespace-nowrap px-3 py-2">
												{f.action === 'approved' ? (
													<Badge variant="default">
														<Check /> {ACTION_LABELS[f.action]}
													</Badge>
												) : (
													<Badge variant="destructive">
														<Undo2 /> {ACTION_LABELS[f.action]}
													</Badge>
												)}
											</td>
											<td className="max-w-72 px-3 py-2">
												<span className="line-clamp-2 whitespace-pre-wrap">{f.comment}</span>
											</td>
											<td className="whitespace-nowrap px-3 py-2 text-xs text-muted-foreground">
												{f.approver}
											</td>
										</tr>
									))}
								</tbody>
							</table>
						)}
					</CardContent>
				</Card>
			</div>
		</div>
	);
}
