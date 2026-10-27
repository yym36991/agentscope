import {
	useInfiniteQuery,
	useMutation,
	useQuery,
	useQueryClient,
} from '@tanstack/react-query';
import {
	Loader2,
	Package,
	Plug,
	Plus,
	Search,
	Trash2,
	Wand2,
} from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

import { api, type HubCard } from '@/api/platform';
import { useAuth } from '@/auth';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
	Card,
	CardDescription,
	CardContent,
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
import { cn } from '@/lib/utils';

/**
 * 资源中心 · MCP / 技能 Hub：浏览运行时注册的 hub，安装进 sys:runtime
 * 名下的共享库（六个阶段的智能体都能用）。浏览对全体成员开放，
 * 安装、停用、删除只有管理员可以 —— L1 中继层做权限门。
 */
function HubBrowser({ kind }: { kind: 'mcp' | 'skill' }) {
	const { user } = useAuth();
	const isAdmin = user?.role === 'admin';
	const queryClient = useQueryClient();
	const isMcp = kind === 'mcp';

	// ---------- hubs & cards ----------
	const hubs = useQuery({
		queryKey: [kind, 'hubs'],
		queryFn: isMcp ? api.listMcpHubs : api.listSkillHubs,
	});
	const [hubId, setHubId] = useState<string | null>(null);
	const activeHub =
		hubs.data?.find((h) => h.hub_id === hubId) ?? hubs.data?.[0] ?? null;

	const [qDraft, setQDraft] = useState('');
	const [q, setQ] = useState('');
	const cards = useInfiniteQuery({
		queryKey: [kind, 'hub-cards', activeHub?.hub_id, q],
		queryFn: ({ pageParam }) =>
			(isMcp ? api.listMcpCards : api.listSkillCards)(activeHub!.hub_id, {
				q: q || undefined,
				cursor: pageParam,
				limit: 20,
			}),
		enabled: !!activeHub,
		initialPageParam: undefined as string | undefined,
		getNextPageParam: (last) => last.next_cursor ?? undefined,
	});
	const allCards = cards.data?.pages.flatMap((p) => p.cards) ?? [];

	// ---------- install (admin) ----------
	const [installing, setInstalling] = useState<HubCard | null>(null);
	const [installName, setInstallName] = useState('');
	const [values, setValues] = useState<Record<string, string>>({});
	const inputKeys = Object.keys(installing?.inputs_schema?.properties ?? {});
	const install = useMutation({
		mutationFn: () => {
			const filled = Object.fromEntries(
				Object.entries(values).filter(([, v]) => v !== ''),
			);
			return isMcp
				? api.installMcp(
						activeHub!.hub_id,
						installing!.id,
						installName.trim() || undefined,
						filled,
					)
				: api.installSkill(
						activeHub!.hub_id,
						installing!.id,
						installName.trim() || undefined,
					);
		},
		onSuccess: (item) => {
			toast.success(`「${item.display_name ?? item.name}」已安装到共享库`);
			setInstalling(null);
			queryClient.invalidateQueries({ queryKey: [kind, 'library'] });
		},
		onError: (err) => toast.error(err.message),
	});
	const openInstall = (card: HubCard) => {
		setInstallName('');
		setValues({});
		setInstalling(card);
	};

	// ---------- shared library ----------
	const lib = useQuery({
		queryKey: [kind, 'library'],
		queryFn: isMcp ? api.listMcpLibrary : api.listSkillLibrary,
	});
	const removeLib = useMutation({
		mutationFn: (id: string) => (isMcp ? api.deleteMcp(id) : api.deleteSkill(id)),
		onSuccess: () => {
			toast.success('已从共享库移除');
			queryClient.invalidateQueries({ queryKey: [kind, 'library'] });
		},
		onError: (err) => toast.error(err.message),
	});
	const toggleMcp = useMutation({
		mutationFn: (v: { id: string; enabled: boolean }) =>
			api.updateMcp(v.id, { enabled: v.enabled }),
		onSuccess: () => queryClient.invalidateQueries({ queryKey: ['mcp', 'library'] }),
		onError: (err) => toast.error(err.message),
	});

	return (
		<div className="h-full overflow-auto p-6">
			<div className="mx-auto max-w-5xl space-y-6">
				<div className="flex items-center gap-2.5">
					<span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
						{isMcp ? <Plug className="size-4.5" /> : <Wand2 className="size-4.5" />}
					</span>
					<div>
						<h1 className="text-lg font-semibold">{isMcp ? 'MCP Hub' : '技能 Hub'}</h1>
						<p className="text-xs text-muted-foreground">
							浏览 hub 里的扩展能力，安装进共享库后六个阶段的智能体都能调用；浏览对全体成员开放，安装与管理需要管理员。
						</p>
					</div>
				</div>

				{/* 已安装的共享库 */}
				<section className="space-y-2">
					<h2 className="flex items-center gap-1.5 text-sm font-semibold">
						<Package className="size-4 text-primary" /> 已安装（{lib.data?.length ?? 0}）
					</h2>
					{lib.isLoading && <p className="text-xs text-muted-foreground">加载中…</p>}
					{lib.data?.length === 0 && (
						<p className="text-xs text-muted-foreground">共享库还是空的，从下面的 hub 里挑一个装上吧。</p>
					)}
					<div className="space-y-1.5">
						{lib.data?.map((item) => (
							<div
								key={item.id}
								className="flex items-center gap-3 rounded-lg border bg-card px-3 py-2"
							>
								<div className="min-w-0 flex-1">
									<div className="flex items-center gap-2">
										<span className="truncate text-sm font-medium">
											{item.display_name ?? item.name}
										</span>
										<Badge variant={item.enabled ? 'default' : 'secondary'}>
											{item.enabled ? '已启用' : '已停用'}
										</Badge>
									</div>
									<p className="truncate text-xs text-muted-foreground">
										{item.description || item.tags.join('、') || item.name}
									</p>
								</div>
								{isAdmin && (
									<div className="flex shrink-0 gap-1.5">
										{isMcp && (
											<Button
												size="sm"
												variant="outline"
												disabled={toggleMcp.isPending}
												onClick={() =>
													toggleMcp.mutate({ id: item.id, enabled: !item.enabled })
												}
											>
												{item.enabled ? '停用' : '启用'}
											</Button>
										)}
										<Button
											size="sm"
											variant="outline"
											className="px-2 text-destructive"
											title="从共享库移除"
											disabled={removeLib.isPending}
											onClick={() => removeLib.mutate(item.id)}
										>
											<Trash2 className="size-3.5" />
										</Button>
									</div>
								)}
							</div>
						))}
					</div>
				</section>

				{/* hub 浏览 */}
				<section className="space-y-3">
					{hubs.data && hubs.data.length > 1 && (
						<div className="flex gap-1.5">
							{hubs.data.map((h) => (
								<button
									key={h.hub_id}
									type="button"
									onClick={() => setHubId(h.hub_id)}
									className={cn(
										'rounded-full border px-3 py-1 text-xs transition-colors',
										activeHub?.hub_id === h.hub_id
											? 'border-primary/50 bg-primary/10 text-primary'
											: 'text-muted-foreground hover:bg-primary/5',
									)}
								>
									{h.display_name}
								</button>
							))}
						</div>
					)}
					<form
						className="flex gap-2"
						onSubmit={(e) => {
							e.preventDefault();
							setQ(qDraft.trim());
						}}
					>
						<div className="relative flex-1">
							<Search className="absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
							<Input
								className="pl-8"
								placeholder={isMcp ? '搜索 MCP，如 markitdown…' : '搜索技能…'}
								value={qDraft}
								onChange={(e) => setQDraft(e.target.value)}
							/>
						</div>
						<Button type="submit" size="sm" variant="outline">
							搜索
						</Button>
					</form>
					{activeHub?.description && (
						<p className="text-xs text-muted-foreground">{activeHub.description}</p>
					)}

					{cards.isLoading && <p className="text-xs text-muted-foreground">加载中…</p>}
					<div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
						{allCards.map((card) => (
							<Card key={card.id} className="flex flex-col">
								<CardHeader className="pb-2">
									<CardTitle className="flex items-start justify-between gap-2 text-sm">
										<span className="min-w-0 truncate">{card.name}</span>
										{card.auth === 'inputs' && (
											<Badge variant="secondary" className="shrink-0">
												需配置
											</Badge>
										)}
									</CardTitle>
									{card.author && <CardDescription className="text-xs">by {card.author}</CardDescription>}
								</CardHeader>
								<CardContent className="flex flex-1 flex-col gap-2">
									<p className="line-clamp-3 flex-1 text-xs leading-relaxed text-muted-foreground">
										{card.description}
									</p>
									<div className="flex items-center justify-between gap-2">
										<div className="flex min-w-0 flex-wrap gap-1">
											{(card.tags ?? []).slice(0, 3).map((t) => (
												<Badge key={t} variant="outline" className="px-1.5 py-0 text-[10px]">
													{t}
												</Badge>
											))}
										</div>
										<span className="shrink-0 text-[10px] text-muted-foreground">
											{card.installs ?? 0} 次安装
										</span>
									</div>
									{isAdmin && (
										<Button size="sm" className="w-full" onClick={() => openInstall(card)}>
											<Plus className="size-3.5" /> 安装
										</Button>
									)}
								</CardContent>
							</Card>
						))}
					</div>
					{cards.hasNextPage && (
						<Button
							variant="outline"
							size="sm"
							className="w-full"
							disabled={cards.isFetchingNextPage}
							onClick={() => cards.fetchNextPage()}
						>
							{cards.isFetchingNextPage && <Loader2 className="size-4 animate-spin" />} 加载更多
						</Button>
					)}
					{!cards.isLoading && allCards.length === 0 && (
						<p className="py-6 text-center text-xs text-muted-foreground">没有匹配的卡片。</p>
					)}
				</section>
			</div>

			{/* 安装对话框：MCP 卡片按 inputs_schema 出配置表单，技能只需可选名称 */}
			<Dialog open={!!installing} onOpenChange={(open) => !open && setInstalling(null)}>
				<DialogContent>
					<DialogHeader>
						<DialogTitle>安装「{installing?.name}」</DialogTitle>
						<DialogDescription>
							安装到共享库后，六个阶段的智能体都能调用。填写的内容（如 API Key）只保存在服务端配置里，不会出现在任何列表或详情中。
						</DialogDescription>
					</DialogHeader>
					<div className="space-y-3">
						<div className="space-y-1.5">
							<Label>安装名称（可选）</Label>
							<Input
								value={installName}
								onChange={(e) => setInstallName(e.target.value)}
								placeholder={installing?.name}
							/>
						</div>
						{inputKeys.map((key) => (
							<div key={key} className="space-y-1.5">
								<Label>{installing?.inputs_schema?.properties?.[key]?.title ?? key}</Label>
								<Input
									value={values[key] ?? ''}
									onChange={(e) => setValues({ ...values, [key]: e.target.value })}
									placeholder={key}
								/>
							</div>
						))}
					</div>
					<DialogFooter>
						<DialogClose asChild>
							<Button variant="outline">取消</Button>
						</DialogClose>
						<Button disabled={install.isPending} onClick={() => install.mutate()}>
							{install.isPending && <Loader2 className="size-4 animate-spin" />} 安装
						</Button>
					</DialogFooter>
				</DialogContent>
			</Dialog>
		</div>
	);
}

export function McpHubPage() {
	return <HubBrowser kind="mcp" />;
}

export function SkillHubPage() {
	return <HubBrowser kind="skill" />;
}
