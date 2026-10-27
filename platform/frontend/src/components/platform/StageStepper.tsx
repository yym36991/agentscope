import { Check, Circle, CircleDotDashed, Play } from 'lucide-react';
import { Fragment } from 'react';

import {
	STAGE_LABELS,
	STAGE_ORDER,
	type ProjectOut,
	type StageRunOut,
} from '@/api/platform';
import { cn } from '@/lib/utils';

/**
 * The one place that renders the six-stage lifecycle. Two densities:
 * the full interactive timeline for the project page (视图 A 的核心),
 * and the dots locator for project cards / the workbench side panel —
 * so the flow is shown once per screen, not three times.
 */

export type StageState =
	| 'approved'
	| 'in_progress'
	| 'under_review'
	| 'available'
	| 'locked';

export const STAGE_STATE_TEXT: Record<StageState, string> = {
	approved: '已通过',
	in_progress: '进行中',
	under_review: '待审批',
	available: '可开启',
	locked: '未解锁',
};

/** Derive every stage's state from the project + its runs. */
export function computeStageStates(
	project: Pick<ProjectOut, 'current_stage' | 'status'>,
	runs: Pick<StageRunOut, 'stage' | 'status'>[],
): Record<string, StageState> {
	const states: Record<string, StageState> = {};
	for (const stage of STAGE_ORDER) {
		const stageRuns = runs.filter((r) => r.stage === stage);
		if (stageRuns.some((r) => r.status === 'approved')) {
			states[stage] = 'approved';
			continue;
		}
		const active = stageRuns.find(
			(r) => r.status === 'in_progress' || r.status === 'under_review',
		);
		if (active) {
			states[stage] = active.status === 'in_progress' ? 'in_progress' : 'under_review';
			continue;
		}
		const isNext =
			project.current_stage === 'none'
				? stage === 'requirement'
				: stage === project.current_stage;
		states[stage] = isNext && project.status !== 'accepted' ? 'available' : 'locked';
	}
	return states;
}

/** Approximation for lists, where per-project runs are not fetched:
 * everything before the current stage counts as approved. */
export function approxStageStates(project: Pick<ProjectOut, 'current_stage' | 'status'>): Record<string, StageState> {
	const idx = STAGE_ORDER.indexOf(project.current_stage as (typeof STAGE_ORDER)[number]);
	const states: Record<string, StageState> = {};
	STAGE_ORDER.forEach((s, i) => {
		if (project.status === 'accepted') states[s] = 'approved';
		else if (idx >= 0 && i < idx) states[s] = 'approved';
		else if (i === idx) states[s] = project.status === 'active' ? 'in_progress' : 'available';
		else states[s] = 'locked';
	});
	return states;
}

const DOT_CLS: Record<StageState, string> = {
	approved: 'bg-primary',
	in_progress: 'bg-primary animate-pulse',
	under_review: 'bg-amber-500',
	available: 'bg-border',
	locked: 'bg-border',
};

/** Locator dots: approved fills left-to-right, the live stage pulses. */
export function StageProgressDots({
	states,
	className,
}: {
	states: Record<string, StageState>;
	className?: string;
}) {
	return (
		<div className={cn('flex items-center', className)}>
			{STAGE_ORDER.map((s, i) => (
				<Fragment key={s}>
					{i > 0 && <span className="h-px w-3 shrink-0 bg-border" />}
					<span
						title={`${STAGE_LABELS[s]} · ${STAGE_STATE_TEXT[states[s] ?? 'locked']}`}
						className={cn('size-2 shrink-0 rounded-full', DOT_CLS[states[s] ?? 'locked'])}
					/>
				</Fragment>
			))}
		</div>
	);
}

/** Full timeline: clickable steps (to inspect a stage's runs), the
 * current stage emphasized, connector bars filled up to the frontier. */
export function StageTimeline({
	states,
	selected,
	onSelect,
}: {
	states: Record<string, StageState>;
	selected?: string;
	onSelect?: (stage: string) => void;
}) {
	return (
		<div className="flex items-start">
			{STAGE_ORDER.map((s, i) => {
				const state = states[s] ?? 'locked';
				const done = state === 'approved';
				const live = state === 'in_progress' || state === 'under_review';
				const isSelected = selected === s;
				const clickable = !!onSelect && (done || live);
				return (
					<Fragment key={s}>
						{i > 0 && (
							<span
								className={cn(
									'mt-4 h-0.5 flex-1 rounded-full',
									done || live ? 'bg-primary/60' : 'bg-border',
								)}
							/>
						)}
						<button
							type="button"
							disabled={!clickable}
							onClick={() => clickable && onSelect?.(s)}
							className={cn(
								'flex w-20 shrink-0 flex-col items-center gap-1.5 rounded-lg px-1 py-2 text-center transition-colors',
								clickable && 'cursor-pointer hover:bg-primary/5',
								isSelected && 'bg-primary/10',
							)}
						>
							{done ? (
								<span className="flex size-8 items-center justify-center rounded-full bg-primary text-primary-foreground">
									<Check className="size-4" />
								</span>
							) : live ? (
								<span className="flex size-8 items-center justify-center rounded-full border-2 border-primary text-primary">
									<CircleDotDashed className={cn('size-4', state === 'in_progress' && 'animate-spin')} />
								</span>
							) : (
								<span className="flex size-8 items-center justify-center rounded-full border-2 border-border text-muted-foreground">
									{state === 'available' ? (
										<Play className="size-3.5" />
									) : (
										<Circle className="size-3" />
									)}
								</span>
							)}
							<span
								className={cn(
									'text-xs font-medium',
									done || live ? 'text-foreground' : 'text-muted-foreground',
								)}
							>
								{STAGE_LABELS[s]}
							</span>
							<span
								className={cn(
									'text-[10px]',
									done
										? 'text-primary'
										: state === 'in_progress'
											? 'text-primary'
											: state === 'under_review'
												? 'text-amber-600'
												: 'text-muted-foreground',
								)}
							>
								{STAGE_STATE_TEXT[state]}
							</span>
						</button>
					</Fragment>
				);
			})}
		</div>
	);
}
