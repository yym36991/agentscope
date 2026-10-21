import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { ToolCallBlock } from '@agentscope-ai/agentscope/message';
import {
	ArrowLeft,
	CheckCheck,
	Download,
	FileText,
	Loader2,
	Send,
	ShieldQuestion,
	X,
} from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { toast } from 'sonner';

import { api, askingToolCalls, STAGE_LABELS, STAGE_ORDER } from '@/api/platform';
import { ASMessageBubble } from '@/components/chat/ASMessageBubble';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import {
	ResizableHandle,
	ResizablePanel,
	ResizablePanelGroup,
} from '@/components/ui/resizable';
import { Markdown } from '@/components/markdown';

const RUN_STATUS: Record<string, string> = {
	in_progress: '进行中',
	under_review: '待审批',
	approved: '已通过',
	returned: '已退回',
};

/**
 * 视图 B：Agent 工作台（类 WorkBuddy 三栏）。
 * 左：项目/阶段上下文；中：与阶段智能体的对话（轮询）；右：产物面板。
 */
export function WorkbenchPage() {
	const { projectId, runId } = useParams();
	const pid = Number(projectId);
	const rid = Number(runId);
	const queryClient = useQueryClient();

	const project = useQuery({ queryKey: ['project', pid], queryFn: () => api.getProject(pid) });
	const run = useQuery({ queryKey: ['run', rid], queryFn: () => api.listStageRuns(pid) });
	const currentRun = (run.data ?? []).find((r) => r.id === rid);
	const artifacts = useQuery({
		queryKey: ['artifacts', rid],
		queryFn: () => api.listRunArtifacts(rid),
		refetchInterval: 8000,
	});

	const messages = useQuery({
		queryKey: ['messages', rid],
		queryFn: () => api.messages(rid),
		// Poll faster while the agent is producing or waiting on HITL.
		refetchInterval: (query) => {
			const data = query.state.data;
			const asking = askingToolCalls(data?.messages?.at(-1)).length > 0;
			return data?.is_running || asking ? 1500 : 4000;
		},
	});

	const asking = askingToolCalls(messages.data?.messages?.at(-1));
	const visible = (messages.data?.messages ?? []).filter(
		(m) => m.role === 'user' || m.role === 'assistant',
	);

	// ---------- send ----------

	const [draft, setDraft] = useState('');
	const chat = useMutation({
		mutationFn: (content: string) => api.chat(rid, content),
		onSuccess: () => {
			setDraft('');
			queryClient.invalidateQueries({ queryKey: ['messages', rid] });
		},
		onError: (err) => toast.error(err.message),
	});

	const confirm = useMutation({
		mutationFn: ({
			block,
			ok,
			allowAll,
		}: {
			block?: ToolCallBlock;
			ok: boolean;
			allowAll?: boolean;
		}) => api.confirm(rid, ok, block ? [block.id] : undefined, allowAll),
		onSuccess: () => queryClient.invalidateQueries({ queryKey: ['messages', rid] }),
		onError: (err) => toast.error(err.message),
	});

	// ---------- artifacts ----------

	const [title, setTitle] = useState('');
	const [preview, setPreview] = useState<number | null>(null);
	const previewQuery = useQuery({
		queryKey: ['artifact', preview],
		queryFn: () => api.getRunArtifact(rid, preview!),
		enabled: preview !== null,
	});
	const workspaceFiles = useQuery({
		queryKey: ['workspace-files', rid],
		queryFn: () => api.listWorkspaceFiles(rid),
		enabled: (run.data ?? []).some((r) => r.id === rid && r.session_id),
		refetchInterval: 8000,
	});
	const [selectedFile, setSelectedFile] = useState('');
	const submitFile = useMutation({
		mutationFn: () => api.submitFile(rid, title.trim(), selectedFile),
		onSuccess: (a) => {
			toast.success(`产物已提交送审：${a.title}`);
			setTitle('');
			setSelectedFile('');
			setPreview(a.id);
			queryClient.invalidateQueries({ queryKey: ['artifacts', rid] });
			queryClient.invalidateQueries({ queryKey: ['run', rid] });
		},
		onError: (err) => toast.error(err.message),
	});
	const submitLatest = useMutation({
		mutationFn: () => api.submitLatest(rid, title.trim()),
		onSuccess: (a) => {
			toast.success(`产物已提交送审：${a.title}`);
			setTitle('');
			setPreview(a.id);
			queryClient.invalidateQueries({ queryKey: ['artifacts', rid] });
			queryClient.invalidateQueries({ queryKey: ['run', rid] });
		},
		onError: (err) => toast.error(err.message),
	});

	// ---------- auto-scroll ----------

	const scrollerRef = useRef<HTMLDivElement>(null);
	const lastSignature = useRef('');
	useEffect(() => {
		const sig = `${visible.length}:${messages.data?.is_running ?? false}:${
			messages.data?.messages?.at(-1)?.content?.length ?? 0
		}`;
		if (sig !== lastSignature.current) {
			lastSignature.current = sig;
			const el = scrollerRef.current;
			if (el) el.scrollTop = el.scrollHeight;
		}
	}, [visible.length, messages.data]);

	if (!currentRun) return <p className="p-6 text-sm text-muted-foreground">加载中…</p>;
	const inProgress = currentRun.status === 'in_progress';

	return (
		<ResizablePanelGroup orientation="horizontal" className="h-full">
			{/* 左栏：阶段上下文 */}
			<ResizablePanel defaultSize="20%" minSize="14rem">
				<div className="flex h-full flex-col gap-4 overflow-auto border-r p-4">
					<Button variant="ghost" size="sm" className="w-fit -ml-2" asChild>
						<Link to={`/projects/${pid}`}>
							<ArrowLeft /> 返回项目
						</Link>
					</Button>
					<div>
						<div className="text-sm font-semibold">{project.data?.name ?? '…'}</div>
						<div className="mt-1 text-xs text-muted-foreground">
							{STAGE_LABELS[currentRun.stage] ?? currentRun.stage} · 第 {currentRun.round} 轮
						</div>
						<Badge className="mt-2" variant={inProgress ? 'default' : 'secondary'}>
							{RUN_STATUS[currentRun.status] ?? currentRun.status}
						</Badge>
					</div>
					<div className="space-y-1.5 text-xs">
						{STAGE_ORDER.map((s) => (
							<div
								key={s}
								className={
									s === currentRun.stage
										? 'rounded bg-primary/10 px-2 py-1 font-medium text-primary'
										: 'px-2 py-1 text-muted-foreground'
								}
							>
								{STAGE_LABELS[s]}
							</div>
						))}
					</div>
				</div>
			</ResizablePanel>

			<ResizableHandle />

			{/* 中栏：对话 */}
			<ResizablePanel defaultSize="52%" minSize="30rem">
				<div className="flex h-full flex-col">
					<div ref={scrollerRef} className="min-h-0 flex-1 space-y-4 overflow-auto p-4">
						{visible.length === 0 && (
							<p className="pt-10 text-center text-sm text-muted-foreground">
								向「{STAGE_LABELS[currentRun.stage] ?? ''}」智能体描述你的需求，开始本阶段工作。
							</p>
						)}
						{visible.map((m) => (
							<ASMessageBubble
								key={m.id ?? `${m.role}-${Math.random()}`}
								message={m}
								onUserConfirm={(block, ok) => confirm.mutate({ block, ok })}
							/>
						))}
						{messages.data?.is_running && visible.length > 0 && (
							<div className="flex items-center gap-2 px-2 text-xs text-muted-foreground">
								<Loader2 className="size-3 animate-spin" /> 智能体正在工作…
							</div>
						)}
					</div>

					{/* HITL 确认条 */}
					{asking.length > 0 && (
						<div className="border-t bg-amber-50 px-4 py-3 dark:bg-amber-950/30">
							<div className="flex items-center gap-2 text-sm font-medium text-amber-900 dark:text-amber-200">
								<ShieldQuestion className="size-4" />
								智能体请求执行 {asking.length} 个工具调用，请确认
								<Button
									size="sm"
									variant="outline"
									className="ml-auto"
									disabled={confirm.isPending}
									onClick={() => confirm.mutate({ ok: true, allowAll: true })}
								>
									<CheckCheck /> 全部允许
								</Button>
							</div>
							<div className="mt-2 space-y-1.5">
								{asking.map((b) => (
									<div key={b.id} className="flex items-center justify-between gap-2 text-xs">
										<code className="rounded bg-amber-100 px-1.5 py-0.5 dark:bg-amber-900">{b.name}</code>
										<span className="flex gap-1">
											<Button
												size="sm"
												variant="outline"
												disabled={confirm.isPending}
												onClick={() => confirm.mutate({ block: b, ok: false })}
											>
												<X /> 拒绝
											</Button>
											<Button
												size="sm"
												disabled={confirm.isPending}
												onClick={() => confirm.mutate({ block: b, ok: true })}
											>
												<CheckCheck /> 允许
											</Button>
										</span>
									</div>
								))}
							</div>
						</div>
					)}

					{/* 输入区 */}
					<div className="border-t p-3">
						<form
							onSubmit={(e) => {
								e.preventDefault();
								if (draft.trim() && !messages.data?.is_running) chat.mutate(draft.trim());
							}}
							className="flex items-end gap-2"
						>
							<textarea
								className="max-h-40 min-h-10 flex-1 resize-none rounded-md border bg-transparent px-3 py-2 text-sm outline-none focus-visible:ring-1 focus-visible:ring-ring"
								placeholder={
									inProgress
										? messages.data?.is_running
											? '智能体正在回复…'
											: '输入消息，Enter 发送，Shift+Enter 换行'
										: '该阶段不在进行中，对话已冻结'
								}
								value={draft}
								disabled={!inProgress || messages.data?.is_running}
								onChange={(e) => setDraft(e.target.value)}
								onKeyDown={(e) => {
									if (e.key === 'Enter' && !e.shiftKey) {
										e.preventDefault();
										if (draft.trim() && !messages.data?.is_running) chat.mutate(draft.trim());
									}
								}}
								rows={2}
							/>
							<Button type="submit" size="icon" disabled={!draft.trim() || !inProgress || messages.data?.is_running || chat.isPending}>
								{chat.isPending ? <Loader2 className="animate-spin" /> : <Send />}
							</Button>
						</form>
					</div>
				</div>
			</ResizablePanel>

			<ResizableHandle />

			{/* 右栏：产物面板 */}
			<ResizablePanel defaultSize="28%" minSize="18rem">
				<div className="flex h-full flex-col gap-4 overflow-auto border-l p-4">
					<Card>
						<CardHeader>
							<CardTitle className="text-sm">提交产物送审</CardTitle>
						</CardHeader>
						<CardContent className="space-y-2">
							<Input
								placeholder="产物标题，例如：需求规格说明书 v1"
								value={title}
								disabled={!inProgress}
								onChange={(e) => setTitle(e.target.value)}
							/>
							<select
								className="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-input/30"
								value={selectedFile}
								disabled={!inProgress || workspaceFiles.isLoading}
								onChange={(e) => {
									const p = e.target.value;
									setSelectedFile(p);
									// 选中文件后标题为空则用文件名预填
									if (p && !title.trim()) {
										setTitle(p.split('/').pop()!.replace(/\.[^.]+$/, ''));
									}
								}}
							>
								<option value="">
									{workspaceFiles.isLoading
										? '加载工作区文件…'
										: (workspaceFiles.data ?? []).length === 0
											? '工作区暂无产物文件'
											: '选择智能体写入的产物文件'}
								</option>
								{(workspaceFiles.data ?? []).map((f) => (
									<option key={f.path} value={f.path}>
										{f.path}
										{f.size_bytes ? `（${(f.size_bytes / 1024).toFixed(1)}KB）` : ''}
									</option>
								))}
							</select>
							<Button
								className="w-full"
								size="sm"
								disabled={
									!inProgress || !title.trim() || !selectedFile || submitFile.isPending
								}
								onClick={() => submitFile.mutate()}
							>
								{submitFile.isPending && <Loader2 className="animate-spin" />}
								提交选中产物
							</Button>
							<Button
								className="w-full"
								size="sm"
								variant="outline"
								disabled={!inProgress || !title.trim() || submitLatest.isPending}
								onClick={() => submitLatest.mutate()}
							>
								{submitLatest.isPending && <Loader2 className="animate-spin" />}
								提交智能体最新回答（兜底）
							</Button>
							<p className="text-xs text-muted-foreground">
								提交后进入待审批，审批通过则推进到下一阶段；退回则重新开启（轮次 +1）。
							</p>
						</CardContent>
					</Card>

					<Card>
						<CardHeader>
							<CardTitle className="text-sm">
								<FileText className="inline size-4" /> 产物版本
							</CardTitle>
						</CardHeader>
						<CardContent className="space-y-1.5">
							{(artifacts.data ?? []).length === 0 && (
								<p className="text-xs text-muted-foreground">还没有产物。</p>
							)}
							{(artifacts.data ?? []).map((a) => (
								<Button
									key={a.id}
									variant={preview === a.id ? 'secondary' : 'ghost'}
									size="sm"
									className="w-full justify-between font-normal"
									onClick={() => setPreview(preview === a.id ? null : a.id)}
								>
									<span className="truncate">v{a.version_no} · {a.title}</span>
								</Button>
							))}
						</CardContent>
					</Card>

					{preview !== null && previewQuery.data && (
						<Card className="min-h-0">
							<CardHeader className="flex-row items-center justify-between space-y-0">
								<CardTitle className="truncate text-sm">{previewQuery.data.title}</CardTitle>
								<Button
									size="sm"
									variant="outline"
									className="shrink-0"
									onClick={() => {
										const a = previewQuery.data!;
										const isHtml = a.format === 'html';
										const blob = new Blob([a.content], {
											type: isHtml
												? 'text/html;charset=utf-8'
												: 'text/markdown;charset=utf-8',
										});
										const url = URL.createObjectURL(blob);
										const link = document.createElement('a');
										link.href = url;
										link.download = `${a.title}-v${a.version_no}.${a.format}`;
										link.click();
										URL.revokeObjectURL(url);
									}}
								>
									<Download /> 下载
								</Button>
							</CardHeader>
							<CardContent className="max-h-[60vh] overflow-auto text-sm">
								{previewQuery.data.format === 'html' ? (
									<iframe
										title={previewQuery.data.title}
										srcDoc={previewQuery.data.content}
										className="h-[60vh] w-full rounded-md border bg-white"
										sandbox="allow-scripts"
									/>
								) : (
									<Markdown>{previewQuery.data.content}</Markdown>
								)}
							</CardContent>
						</Card>
					)}
				</div>
			</ResizablePanel>
		</ResizablePanelGroup>
	);
}
