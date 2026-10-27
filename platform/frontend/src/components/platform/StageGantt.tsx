import {
	STAGE_LABELS,
	STAGE_ORDER,
	type StageRunOut,
} from '@/api/platform';

interface StageSpan {
	stage: string;
	start: number;
	end: number;
	rounds: number;
	returned: number;
	ongoing: boolean;
}

const fmtDate = (ts: number) =>
	new Date(ts).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' });

const fmtFull = (ts: number) =>
	new Date(ts).toLocaleString('zh-CN', {
		year: 'numeric',
		month: '2-digit',
		day: '2-digit',
		hour: '2-digit',
		minute: '2-digit',
	});

/** 阶段甘特视图：每个阶段一条横条，从首轮运行创建画到审批决定
 *  （未收尾的阶段画到当前时间、用浅色），条尾标注轮次与退回次数。
 *  单一色相、细条、日期刻度用细实线网格。 */
export function StageGantt({ runs }: { runs: StageRunOut[] }) {
	const spans: StageSpan[] = [];
	for (const stage of STAGE_ORDER) {
		const stageRuns = runs.filter((r) => r.stage === stage);
		if (stageRuns.length === 0) continue;
		const start = Math.min(...stageRuns.map((r) => new Date(r.created_at).getTime()));
		const decided = stageRuns
			.filter((r) => r.decided_at)
			.map((r) => new Date(r.decided_at!).getTime());
		const last = stageRuns.reduce((a, b) => (a.round > b.round ? a : b));
		const ongoing = !decided.length || last.status !== 'approved';
		const end = ongoing ? Date.now() : Math.max(...decided);
		spans.push({
			stage,
			start,
			end,
			rounds: last.round,
			returned: stageRuns.filter((r) => r.status === 'returned').length,
			ongoing,
		});
	}
	if (spans.length === 0) return null;

	const min = Math.min(...spans.map((s) => s.start));
	const max = Math.max(...spans.map((s) => s.end), min + 1);
	const span = max - min;
	const pos = (t: number) => ((t - min) / span) * 100;

	// 4 条等距日期刻度（含首尾）
	const ticks = [0, 1, 2, 3].map((i) => min + (span * i) / 3);

	return (
		<div>
			<div className="relative">
				{/* 日期刻度的细实线网格，压在条形下方 */}
				{ticks.map((t, i) => (
					<div
						key={i}
						className="pointer-events-none absolute inset-y-0 border-l border-border/70"
						style={{ left: `${pos(t)}%` }}
					/>
				))}
				<div className="relative space-y-2.5 py-1">
					{spans.map((s) => (
						<div key={s.stage} className="flex items-center gap-3">
							<span className="w-16 shrink-0 text-sm">{STAGE_LABELS[s.stage] ?? s.stage}</span>
							<div className="relative h-5 min-w-0 flex-1">
								<div
									className={`absolute inset-y-0 rounded-md transition-opacity hover:opacity-75 ${
										s.ongoing ? 'bg-primary/35' : 'bg-primary'
									}`}
									style={{
										left: `${pos(s.start)}%`,
										width: `${Math.max(pos(s.end) - pos(s.start), 1)}%`,
									}}
									title={`${STAGE_LABELS[s.stage] ?? s.stage}：${fmtFull(s.start)} → ${fmtFull(s.end)}${s.ongoing ? '（进行中）' : ''}，共 ${s.rounds} 轮`}
								/>
							</div>
							<span className="w-24 shrink-0 text-right text-xs whitespace-nowrap tabular-nums text-muted-foreground">
								{s.rounds} 轮
								{s.returned > 0 && ` · 退回 ${s.returned}`}
								{s.ongoing && ' · 进行中'}
							</span>
						</div>
					))}
				</div>
			</div>
			{/* 时间轴标签行：与上方刻度对齐 */}
			<div className="mt-1 flex items-center gap-3">
				<span className="w-16 shrink-0" />
				<div className="relative h-4 min-w-0 flex-1">
					{ticks.map((t, i) => (
						<span
							key={i}
							className={`absolute top-0 text-[10px] text-muted-foreground ${i === 0 ? '' : '-translate-x-1/2'}`}
							style={{ left: `${pos(t)}%` }}
						>
							{fmtDate(t)}
						</span>
					))}
				</div>
				<span className="w-24 shrink-0" />
			</div>
		</div>
	);
}
