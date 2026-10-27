import { useQuery } from '@tanstack/react-query';

import { api } from '@/api/platform';

/** 功能点与追溯矩阵（§7.3）：需求 → 功能点 → 测试用例 → 工时报价
 *  贯通视图。数据在阶段审批通过时从运行工作区的结构化侧表收割入库，
 *  展示每阶段最新已批准轮次；NESMA 估算功能点法权重（ILF=7 / EIF=5 /
 *  EI=4 / EO=5 / EQ=4）由平台定价，智能体只负责分类。 */
export function TraceMatrix({ projectId }: { projectId: number }) {
	const trace = useQuery({
		queryKey: ['trace', projectId],
		queryFn: () => api.getTrace(projectId),
	});

	if (trace.isLoading) return <p className="text-xs text-muted-foreground">加载中…</p>;
	if (trace.isError)
		return <p className="text-xs text-destructive">加载失败：{trace.error?.message}</p>;
	const t = trace.data;
	if (!t) return null;

	if (t.function_points.length === 0 && t.requirements.length === 0) {
		return (
			<p className="text-xs text-muted-foreground">
				还没有可追溯的结构化数据。各阶段智能体在产出文档的同时会写一份机器可读侧表
				（req/fp/tc/budget-table.json），阶段审批通过后自动收割入库 ——
				新跑一轮并审批通过即可在这里看到贯通视图。
			</p>
		);
	}

	return (
		<div className="space-y-4">
			<div className="flex flex-wrap items-end gap-x-8 gap-y-2">
				<div>
					<p className="text-xs text-muted-foreground">未调整功能点（UFP）</p>
					<p className="text-3xl font-semibold">{t.ufp}</p>
				</div>
				{t.hours_total !== null && (
					<div>
						<p className="text-xs text-muted-foreground">功能点工时合计</p>
						<p className="text-3xl font-semibold">{t.hours_total.toLocaleString()} 小时</p>
					</div>
				)}
				<div>
					<p className="text-xs text-muted-foreground">覆盖情况</p>
					<p className="text-sm">
						{t.requirements.length} 条需求 · {t.function_points.length} 个功能点 ·{' '}
						{t.test_cases.length} 条用例
					</p>
				</div>
			</div>

			{t.function_points.length > 0 && (
				<div className="overflow-x-auto">
					<table className="w-full text-sm">
						<thead>
							<tr className="border-b text-left text-xs text-muted-foreground">
								<th className="px-2 py-1.5 font-medium">编号</th>
								<th className="px-2 py-1.5 font-medium">功能点</th>
								<th className="px-2 py-1.5 font-medium">类别</th>
								<th className="px-2 py-1.5 font-medium">复杂度</th>
								<th className="px-2 py-1.5 text-right font-medium">权重</th>
								<th className="px-2 py-1.5 text-right font-medium">工时</th>
								<th className="px-2 py-1.5 font-medium">追溯需求</th>
								<th className="px-2 py-1.5 font-medium">覆盖用例</th>
							</tr>
						</thead>
						<tbody>
							{t.function_points.map((fp) => {
								const tcs = t.test_cases.filter((tc) => tc.fp_refs.includes(fp.fp_id));
								return (
									<tr key={fp.fp_id} className="border-b last:border-0 hover:bg-row-hover">
										<td className="px-2 py-1.5 font-mono text-xs">{fp.fp_id}</td>
										<td className="px-2 py-1.5">{fp.name}</td>
										<td className="px-2 py-1.5 text-xs text-muted-foreground">{fp.category}</td>
										<td className="px-2 py-1.5 text-xs text-muted-foreground">
											{fp.complexity ?? '—'}
										</td>
										<td className="px-2 py-1.5 text-right tabular-nums">{fp.weight}</td>
										<td className="px-2 py-1.5 text-right tabular-nums">
											{fp.hours === null ? '—' : `${fp.hours} 小时`}
										</td>
										<td className="px-2 py-1.5 font-mono text-xs text-muted-foreground">
											{fp.fr_refs.length ? fp.fr_refs.join('、') : '—'}
										</td>
										<td className="px-2 py-1.5 font-mono text-xs text-muted-foreground">
											{tcs.length ? (
												<span title={tcs.map((tc) => `${tc.tc_id} ${tc.title}`).join('\n')}>
													{tcs.map((tc) => tc.tc_id).join('、')}
												</span>
											) : (
												'—'
											)}
										</td>
									</tr>
								);
							})}
						</tbody>
					</table>
				</div>
			)}

			{t.requirements.length > 0 && (
				<details className="rounded-lg border px-3 py-2">
					<summary className="cursor-pointer text-sm font-medium">
						需求清单（{t.requirements.length} 条）
					</summary>
					<ul className="mt-2 space-y-1.5">
						{t.requirements.map((r) => (
							<li key={r.req_id} className="text-sm">
								<span className="font-mono text-xs text-muted-foreground">{r.req_id}</span>{' '}
								<span className="font-medium">{r.title}</span>
								{r.summary && <span className="ml-1 text-xs text-muted-foreground">—— {r.summary}</span>}
							</li>
						))}
					</ul>
				</details>
			)}
		</div>
	);
}
