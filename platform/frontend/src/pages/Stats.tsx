import { useQuery } from '@tanstack/react-query';
import { BarChart3 } from 'lucide-react';

import {
	api,
	PROJECT_STATUS_LABELS,
	STAGE_LABELS,
	type StatsOut,
} from '@/api/platform';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

/** 横向条形行：单一色相（主色），≤24px 粗，数据端 4px 圆角、基线端直角，
 *  值直接标在条尾（文本用正文色，不穿数据色）。 */
function BarRow({
	label,
	value,
	max,
	valueText,
	title,
}: {
	label: string;
	value: number;
	max: number;
	valueText: string;
	title: string;
}) {
	const pct = max > 0 ? Math.max((value / max) * 100, value > 0 ? 1.5 : 0) : 0;
	return (
		<div
			className="group flex items-center gap-3 rounded-md px-1 py-1 transition-colors hover:bg-muted/40"
			title={title}
		>
			<span className="w-20 shrink-0 text-sm text-foreground">{label}</span>
			<div className="h-5 min-w-0 flex-1">
				<div
					className="h-5 rounded-l-none rounded-r-md bg-primary transition-opacity group-hover:opacity-75"
					style={{ width: `${pct}%` }}
				/>
			</div>
			<span className="w-16 shrink-0 text-right text-sm tabular-nums text-muted-foreground">
				{valueText}
			</span>
		</div>
	);
}

function StatTile({ label, value, hint }: { label: string; value: string; hint?: string }) {
	return (
		<Card>
			<CardContent className="p-4">
				<p className="text-xs text-muted-foreground">{label}</p>
				<p className="mt-1 text-2xl font-semibold">{value}</p>
				{hint && <p className="mt-0.5 text-xs text-muted-foreground/80">{hint}</p>}
			</CardContent>
		</Card>
	);
}

function StatusChart({ data }: { data: StatsOut }) {
	const entries = Object.entries(data.projects_by_status);
	if (entries.length === 0) return <p className="text-xs text-muted-foreground">暂无项目。</p>;
	const max = Math.max(...entries.map(([, v]) => v), 1);
	return (
		<div className="space-y-1.5">
			{entries.map(([status, count]) => (
				<BarRow
					key={status}
					label={PROJECT_STATUS_LABELS[status] ?? status}
					value={count}
					max={max}
					valueText={`${count} 个`}
					title={`${PROJECT_STATUS_LABELS[status] ?? status}：${count} 个项目`}
				/>
			))}
		</div>
	);
}

function StageHoursChart({ data }: { data: StatsOut }) {
	const withHours = data.stages.filter((s) => s.avg_hours !== null);
	if (withHours.length === 0)
		return <p className="text-xs text-muted-foreground">还没有已通过的阶段运行。</p>;
	const max = Math.max(...withHours.map((s) => s.avg_hours ?? 0));
	return (
		<div className="space-y-1.5">
			{data.stages.map((s) => (
				<BarRow
					key={s.stage}
					label={STAGE_LABELS[s.stage] ?? s.stage}
					value={s.avg_hours ?? 0}
					max={max}
					valueText={s.avg_hours === null ? '—' : `${s.avg_hours} 小时`}
					title={`${STAGE_LABELS[s.stage] ?? s.stage}：平均 ${s.avg_hours ?? '—'} 小时（${s.approved} 次通过）`}
				/>
			))}
		</div>
	);
}

function ReturnRateChart({ data }: { data: StatsOut }) {
	const withRuns = data.stages.filter((s) => s.runs > 0);
	if (withRuns.length === 0)
		return <p className="text-xs text-muted-foreground">还没有阶段运行。</p>;
	const max = Math.max(...withRuns.map((s) => s.return_rate), 0.001);
	return (
		<div className="space-y-1.5">
			{data.stages.map((s) => (
				<BarRow
					key={s.stage}
					label={STAGE_LABELS[s.stage] ?? s.stage}
					value={s.return_rate}
					max={max}
					valueText={s.runs === 0 ? '—' : `${(s.return_rate * 100).toFixed(1)}%`}
					title={`${STAGE_LABELS[s.stage] ?? s.stage}：${s.returned}/${s.runs} 次退回`}
				/>
			))}
		</div>
	);
}

/** 管理视图 · 统计看板：项目状态分布、阶段耗时 / 轮次 / 退回率、
 *  审批通过率与价格基准覆盖。管理员看全平台，成员看自己可见的项目。 */
export function StatsPage() {
	const stats = useQuery({ queryKey: ['stats'], queryFn: api.getStats });

	if (stats.isLoading) return <p className="p-6 text-sm text-muted-foreground">加载中…</p>;
	if (stats.isError || !stats.data)
		return <p className="p-6 text-sm text-destructive">加载失败：{stats.error?.message}</p>;
	const d = stats.data;

	const decided = d.approvals.approved + d.approvals.returned;
	const passRate = decided > 0 ? ((d.approvals.approved / decided) * 100).toFixed(1) : '—';

	return (
		<div className="h-full overflow-auto p-6">
			<div className="mx-auto max-w-5xl space-y-4">
				<div className="flex items-center gap-2.5">
					<span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
						<BarChart3 className="size-4.5" />
					</span>
					<div>
						<h1 className="text-lg font-semibold">统计看板</h1>
						<p className="text-xs text-muted-foreground">
							项目状态分布、各阶段平均耗时（首轮创建 → 审批决定）与退回率；管理员看全平台，成员看自己可见的项目。
						</p>
					</div>
				</div>

				<div className="grid grid-cols-2 gap-3 md:grid-cols-5">
					<StatTile label="项目总数" value={String(d.projects_total)} />
					<StatTile label="进行中" value={String(d.projects_by_status.active ?? 0)} />
					<StatTile
						label="审批通过率"
						value={`${passRate}%`}
						hint={`通过 ${d.approvals.approved} / 退回 ${d.approvals.returned} / 待审 ${d.approvals.pending}`}
					/>
					<StatTile label="价格基准条目" value={String(d.price.items)} hint={`${d.price.regions} 个地区`} />
					<StatTile
						label="累计功能点阶段通过"
						value={String(d.stages.reduce((n, s) => n + s.approved, 0))}
					/>
				</div>

				<div className="grid gap-4 md:grid-cols-2">
					<Card>
						<CardHeader>
							<CardTitle className="text-base">项目状态分布</CardTitle>
							<CardDescription>按项目当前状态统计。</CardDescription>
						</CardHeader>
						<CardContent>
							<StatusChart data={d} />
						</CardContent>
					</Card>
					<Card>
						<CardHeader>
							<CardTitle className="text-base">各阶段平均耗时</CardTitle>
							<CardDescription>阶段运行创建到审批决定的平均间隔。</CardDescription>
						</CardHeader>
						<CardContent className="space-y-4">
							<StageHoursChart data={d} />
							<div className="border-t pt-3">
								<p className="mb-1.5 text-xs font-medium text-muted-foreground">各阶段退回率</p>
								<ReturnRateChart data={d} />
							</div>
						</CardContent>
					</Card>
				</div>

				<Card>
					<CardHeader>
						<CardTitle className="text-base">阶段明细</CardTitle>
						<CardDescription>以上图表的完整数据（含轮次），与看板同一数据源。</CardDescription>
					</CardHeader>
					<CardContent className="p-0">
						<table className="w-full text-sm">
							<thead>
								<tr className="border-b text-left text-xs text-muted-foreground">
									<th className="px-3 py-2 font-medium">阶段</th>
									<th className="px-3 py-2 text-right font-medium">运行数</th>
									<th className="px-3 py-2 text-right font-medium">通过</th>
									<th className="px-3 py-2 text-right font-medium">退回</th>
									<th className="px-3 py-2 text-right font-medium">平均耗时</th>
									<th className="px-3 py-2 text-right font-medium">平均轮次</th>
									<th className="px-3 py-2 text-right font-medium">退回率</th>
								</tr>
							</thead>
							<tbody>
								{d.stages.map((s) => (
									<tr key={s.stage} className="border-b last:border-0 hover:bg-row-hover">
										<td className="px-3 py-2">{STAGE_LABELS[s.stage] ?? s.stage}</td>
										<td className="px-3 py-2 text-right tabular-nums">{s.runs}</td>
										<td className="px-3 py-2 text-right tabular-nums">{s.approved}</td>
										<td className="px-3 py-2 text-right tabular-nums">{s.returned}</td>
										<td className="px-3 py-2 text-right tabular-nums">
											{s.avg_hours === null ? '—' : `${s.avg_hours} 小时`}
										</td>
										<td className="px-3 py-2 text-right tabular-nums">
											{s.avg_rounds === null ? '—' : s.avg_rounds}
										</td>
										<td className="px-3 py-2 text-right tabular-nums">
											{s.runs === 0 ? '—' : `${(s.return_rate * 100).toFixed(1)}%`}
										</td>
									</tr>
								))}
							</tbody>
						</table>
					</CardContent>
				</Card>
			</div>
		</div>
	);
}
