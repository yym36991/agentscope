import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
	BookOpen,
	Loader2,
	Plus,
	Search,
	Trash2,
	Upload,
} from 'lucide-react';
import { useRef, useState } from 'react';
import { toast } from 'sonner';

import {
	api,
	KB_TYPE_LABELS,
	type KbOut,
	type KbSearchHit,
} from '@/api/platform';
import { useAuth } from '@/auth';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
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
import { cn } from '@/lib/utils';

/**
 * 资源中心 · 知识库（M3 §7.2）：组授权的共享资料库。列表按可见性过滤
 * （管理员全见）；文档上传与检索都经 L1 代理做权限检查，先过滤后检索。
 */
export function KnowledgeBasesPage() {
	const { user } = useAuth();
	const isAdmin = user?.role === 'admin';
	const queryClient = useQueryClient();

	const kbs = useQuery({ queryKey: ['kbs'], queryFn: api.listKbs });
	const [selectedId, setSelectedId] = useState<number | null>(null);
	const selected = (kbs.data ?? []).find((k) => k.id === selectedId) ?? kbs.data?.[0] ?? null;

	const invalidate = () => queryClient.invalidateQueries({ queryKey: ['kbs'] });

	// ---------- create (admin) ----------
	const [creating, setCreating] = useState(false);
	const [form, setForm] = useState({ name: '', kb_type: 'spec', description: '' });
	const create = useMutation({
		mutationFn: () =>
			api.createKb(form.name.trim(), form.kb_type as KbOut['kb_type'], form.description.trim()),
		onSuccess: (kb) => {
			toast.success(`知识库「${kb.name}」已创建`);
			setCreating(false);
			setForm({ name: '', kb_type: 'spec', description: '' });
			invalidate();
			setSelectedId(kb.id);
		},
		onError: (err) => toast.error(err.message),
	});

	// ---------- delete (admin) ----------
	const [deleting, setDeleting] = useState<KbOut | null>(null);
	const del = useMutation({
		mutationFn: (kbId: number) => api.deleteKb(kbId),
		onSuccess: () => {
			toast.success('知识库已删除');
			setDeleting(null);
			setSelectedId(null);
			invalidate();
		},
		onError: (err) => toast.error(err.message),
	});

	// ---------- documents & search ----------
	const docs = useQuery({
		queryKey: ['kb-docs', selected?.id],
		queryFn: () => api.listKbDocs(selected!.id),
		enabled: !!selected,
		refetchInterval: 15000,
	});
	const fileRef = useRef<HTMLInputElement>(null);
	const upload = useMutation({
		mutationFn: (file: File) => api.uploadKbDoc(selected!.id, file),
		onSuccess: (d) => {
			toast.success(`已上传 ${d.filename}，向量化处理中`);
			queryClient.invalidateQueries({ queryKey: ['kb-docs', selected?.id] });
		},
		onError: (err) => toast.error(err.message),
	});

	const [queryText, setQueryText] = useState('');
	const [searchOpen, setSearchOpen] = useState(false);
	const search = useMutation({
		mutationFn: () => api.searchKb(selected!.id, queryText.trim()),
		onSuccess: () => setSearchOpen(true),
		onError: (err) => toast.error(err.message),
	});

	// ---------- grants (admin) ----------
	const [grantsKb, setGrantsKb] = useState<KbOut | null>(null);
	const groups = useQuery({
		queryKey: ['groups'],
		queryFn: api.listGroups,
		enabled: isAdmin,
	});
	const [grantDraft, setGrantDraft] = useState<Record<number, '' | 'read' | 'write'>>({});
	const openGrants = (kb: KbOut) => {
		const draft: Record<number, '' | 'read' | 'write'> = {};
		for (const g of groups.data ?? []) {
			const cur = kb.grants?.find((x) => x.group_id === g.id);
			draft[g.id] = (cur?.level as 'read' | 'write') ?? '';
		}
		setGrantDraft(draft);
		setGrantsKb(kb);
	};
	const saveGrants = useMutation({
		mutationFn: () =>
			api.setKbGrants(
				grantsKb!.id,
				Object.entries(grantDraft)
					.filter(([, level]) => level !== '')
					.map(([gid, level]) => ({ group_id: Number(gid), level: level as 'read' | 'write' })),
			),
		onSuccess: () => {
			toast.success('授权已更新（写权限自动包含读）');
			setGrantsKb(null);
			invalidate();
		},
		onError: (err) => toast.error(err.message),
	});

	return (
		<div className="flex h-full">
			{/* 左：库列表 */}
			<div className="flex w-72 shrink-0 flex-col border-r bg-card">
				<div className="flex items-center justify-between border-b px-4 py-3">
					<h1 className="text-sm font-semibold">知识库</h1>
					{isAdmin && (
						<Button size="sm" variant="outline" onClick={() => setCreating(true)}>
							<Plus className="size-3.5" /> 新建
						</Button>
					)}
				</div>
				<div className="min-h-0 flex-1 overflow-auto p-2">
					{kbs.isLoading && (
						<p className="p-4 text-xs text-muted-foreground">加载中…</p>
					)}
					{(kbs.data ?? []).length === 0 && !kbs.isLoading && (
						<p className="p-4 text-xs text-muted-foreground">
							{isAdmin ? '还没有知识库，点右上角「新建」创建。' : '你所在的小组还没有被授权任何知识库。'}
						</p>
					)}
					{(kbs.data ?? []).map((kb) => (
						<button
							key={kb.id}
							type="button"
							onClick={() => {
								setSelectedId(kb.id);
								setSearchOpen(false);
							}}
							className={cn(
								'w-full rounded-lg px-3 py-2.5 text-left transition-colors',
								selected?.id === kb.id
									? 'bg-primary/10'
									: 'hover:bg-primary/5',
							)}
						>
							<div className="flex items-center gap-2">
								<BookOpen className="size-4 shrink-0 text-primary" />
								<span className="min-w-0 flex-1 truncate text-sm font-medium">
									{kb.name}
								</span>
							</div>
							<div className="mt-1 flex items-center gap-1.5 pl-6">
								<Badge variant="secondary" className="px-1.5 py-0 text-[10px]">
									{KB_TYPE_LABELS[kb.kb_type] ?? kb.kb_type}
								</Badge>
								{kb.agentscope_kb_id === null && (
									<span className="text-[10px] text-amber-600">未接入</span>
								)}
							</div>
						</button>
					))}
				</div>
			</div>

			{/* 右：库详情 */}
			{!selected ? (
				<div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
					选择左侧的知识库查看文档与检索
				</div>
			) : (
				<div className="min-w-0 flex-1 overflow-auto p-6">
					<div className="mx-auto max-w-3xl space-y-5">
						<div className="flex items-start justify-between gap-3">
							<div>
								<h2 className="flex items-center gap-2 text-lg font-semibold">
									{selected.name}
									<Badge variant="secondary">
										{KB_TYPE_LABELS[selected.kb_type] ?? selected.kb_type}
									</Badge>
								</h2>
								{selected.description && (
									<p className="mt-1 text-sm text-muted-foreground">{selected.description}</p>
								)}
							</div>
							{isAdmin && (
								<div className="flex shrink-0 gap-2">
									<Button size="sm" variant="outline" onClick={() => openGrants(selected)}>
										组授权
									</Button>
									<Button size="sm" variant="outline" className="text-destructive" onClick={() => setDeleting(selected)}>
										<Trash2 className="size-3.5" /> 删除
									</Button>
								</div>
							)}
						</div>

						{selected.agentscope_kb_id === null && (
							<div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-xs leading-relaxed text-amber-800">
								该库还未接入运行时向量库（sys:runtime 名下缺少向量化凭证）：
								可以维护授权与项目绑定，但文档上传与检索要等管理员注册 openai 类型凭证后开放。
							</div>
						)}

						{/* 检索 */}
						<Card>
							<CardHeader>
								<CardTitle className="text-sm">语义检索</CardTitle>
							</CardHeader>
							<CardContent className="space-y-3">
								<form
									className="flex gap-2"
									onSubmit={(e) => {
										e.preventDefault();
										if (queryText.trim()) search.mutate();
									}}
								>
									<div className="relative flex-1">
										<Search className="absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
										<Input
											className="pl-8"
											placeholder="输入问题，检索库内文档片段…"
											value={queryText}
											onChange={(e) => setQueryText(e.target.value)}
										/>
									</div>
									<Button type="submit" size="sm" disabled={!queryText.trim() || search.isPending}>
										{search.isPending ? <Loader2 className="size-4 animate-spin" /> : <Search className="size-4" />}
										检索
									</Button>
								</form>
								{searchOpen && (search.data?.results?.length ?? 0) === 0 && (
									<p className="text-xs text-muted-foreground">没有命中的片段。</p>
								)}
								{searchOpen &&
									(search.data?.results ?? []).map((hit: KbSearchHit, i) => (
										<div key={i} className="rounded-lg border bg-muted/30 px-3 py-2 text-xs leading-relaxed">
											{hit.content ?? hit.text ?? JSON.stringify(hit)}
										</div>
									))}
							</CardContent>
						</Card>

						{/* 文档 */}
						<Card>
							<CardHeader className="flex-row items-center justify-between space-y-0">
								<CardTitle className="text-sm">文档（{docs.data?.length ?? 0}）</CardTitle>
								<div>
									<input
										ref={fileRef}
										type="file"
										hidden
										onChange={(e) => {
											const f = e.target.files?.[0];
											if (f) upload.mutate(f);
											e.target.value = '';
										}}
									/>
									<Button
										size="sm"
										disabled={upload.isPending}
										onClick={() => fileRef.current?.click()}
									>
										{upload.isPending ? <Loader2 className="size-4 animate-spin" /> : <Upload className="size-4" />}
										上传文档
									</Button>
								</div>
							</CardHeader>
							<CardContent>
								{(docs.data ?? []).length === 0 && (
									<p className="text-xs text-muted-foreground">还没有文档。</p>
								)}
								<div className="space-y-1.5">
									{(docs.data ?? []).map((d) => (
										<div key={d.document_id} className="flex items-center justify-between rounded-lg border px-3 py-2 text-sm">
											<span className="min-w-0 flex-1 truncate">{d.filename}</span>
											<Badge
												variant={
													d.status === 'ready'
														? 'default'
														: d.status === 'failed'
															? 'destructive'
															: 'secondary'
												}
											>
												{d.status === 'ready'
													? '已就绪'
													: d.status === 'failed'
														? '处理失败'
														: d.status === 'pending'
															? '排队中'
															: '处理中'}
											</Badge>
										</div>
									))}
								</div>
							</CardContent>
						</Card>
					</div>
				</div>
			)}

			{/* 新建库 */}
			<Dialog open={creating} onOpenChange={setCreating}>
				<DialogContent>
					<DialogHeader>
						<DialogTitle>新建知识库</DialogTitle>
						<DialogDescription>
							创建后由管理员在「组授权」里把库授权给部门小组，项目再按阶段绑定使用。
						</DialogDescription>
					</DialogHeader>
					<div className="space-y-3">
						<div className="space-y-1.5">
							<Label>库名称</Label>
							<Input
								value={form.name}
								onChange={(e) => setForm({ ...form, name: e.target.value })}
								placeholder="例如：北京地区造价评估规范库"
							/>
						</div>
						<div className="space-y-1.5">
							<Label>库类型</Label>
							<Select value={form.kb_type} onValueChange={(v) => setForm({ ...form, kb_type: v })}>
								<SelectTrigger>
									<SelectValue />
								</SelectTrigger>
								<SelectContent>
									{Object.entries(KB_TYPE_LABELS).map(([v, label]) => (
										<SelectItem key={v} value={v}>
											{label}
										</SelectItem>
									))}
								</SelectContent>
							</Select>
						</div>
						<div className="space-y-1.5">
							<Label>描述</Label>
							<Input
								value={form.description}
								onChange={(e) => setForm({ ...form, description: e.target.value })}
								placeholder="可选"
							/>
						</div>
					</div>
					<DialogFooter>
						<DialogClose asChild>
							<Button variant="outline">取消</Button>
						</DialogClose>
						<Button disabled={form.name.trim().length < 2 || create.isPending} onClick={() => create.mutate()}>
							{create.isPending && <Loader2 className="size-4 animate-spin" />} 创建
						</Button>
					</DialogFooter>
				</DialogContent>
			</Dialog>

			{/* 组授权 */}
			<Dialog open={!!grantsKb} onOpenChange={(open) => !open && setGrantsKb(null)}>
				<DialogContent>
					<DialogHeader>
						<DialogTitle>组授权 · {grantsKb?.name}</DialogTitle>
						<DialogDescription>
							按小组授予读 / 写权限（写自动包含读）。未授权的小组及其成员看不到该库。
						</DialogDescription>
					</DialogHeader>
					<div className="max-h-72 space-y-1.5 overflow-auto">
						{(groups.data ?? []).map((g) => (
							<div key={g.id} className="flex items-center justify-between rounded-lg border px-3 py-2 text-sm">
								<span>{g.name}</span>
								<Select
									value={grantDraft[g.id] ?? ''}
									onValueChange={(v) => setGrantDraft({ ...grantDraft, [g.id]: v as '' | 'read' | 'write' })}
								>
									<SelectTrigger className="w-28">
										<SelectValue placeholder="无权限" />
									</SelectTrigger>
									<SelectContent>
										<SelectItem value="read">只读</SelectItem>
										<SelectItem value="write">读写</SelectItem>
									</SelectContent>
								</Select>
							</div>
						))}
					</div>
					<DialogFooter>
						<DialogClose asChild>
							<Button variant="outline">取消</Button>
						</DialogClose>
						<Button disabled={saveGrants.isPending} onClick={() => saveGrants.mutate()}>
							{saveGrants.isPending && <Loader2 className="size-4 animate-spin" />} 保存
						</Button>
					</DialogFooter>
				</DialogContent>
			</Dialog>

			{/* 删除确认 */}
			<Dialog open={!!deleting} onOpenChange={(open) => !open && setDeleting(null)}>
				<DialogContent>
					<DialogHeader>
						<DialogTitle>删除知识库「{deleting?.name}」？</DialogTitle>
						<DialogDescription>
							运行时侧的文档与向量将一并删除，项目绑定自动解除。此操作不可撤销。
						</DialogDescription>
					</DialogHeader>
					<DialogFooter>
						<DialogClose asChild>
							<Button variant="outline">取消</Button>
						</DialogClose>
						<Button variant="destructive" disabled={del.isPending} onClick={() => deleting && del.mutate(deleting.id)}>
							{del.isPending && <Loader2 className="size-4 animate-spin" />} 删除
						</Button>
					</DialogFooter>
				</DialogContent>
			</Dialog>
		</div>
	);
}
