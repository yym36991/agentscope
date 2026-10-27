import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Loader2, Pencil, Plus, Users, X } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

import { api, type AdminUserOut } from '@/api/platform';
import { useAuth } from '@/auth';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
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
import { Switch } from '@/components/ui/switch';

/** 用户编辑草稿：role / is_active / groups 一次提交，display_name 可单独改 */
interface UserDraft {
	display_name: string;
	role: 'admin' | 'member';
	is_active: boolean;
	group_ids: number[];
}

/** 管理视图 · 组织管理（架构 §13 决策 5 的 UI 闭环）：小组 CRUD 与
 *  成员部门调整。小组是知识库授权的载体，调整成员所在小组即调整
 *  其可见的知识库范围。仅管理员可见。 */
export function OrgPage() {
	const { user } = useAuth();
	const isAdmin = user?.role === 'admin';
	const queryClient = useQueryClient();

	const users = useQuery({
		queryKey: ['admin-users'],
		queryFn: api.listAdminUsers,
		enabled: isAdmin,
	});
	const groups = useQuery({ queryKey: ['groups'], queryFn: api.listGroups, enabled: isAdmin });

	const invalidate = () => {
		queryClient.invalidateQueries({ queryKey: ['admin-users'] });
		queryClient.invalidateQueries({ queryKey: ['groups'] });
		// 小组变动改变知识库可见范围，授权矩阵与绑定列表一并刷新
		queryClient.invalidateQueries({ queryKey: ['kbs'] });
	};

	// ---- 用户编辑 ----
	const [editing, setEditing] = useState<AdminUserOut | null>(null);
	const [draft, setDraft] = useState<UserDraft | null>(null);
	const saveUser = useMutation({
		mutationFn: async () => {
			if (!editing || !draft) throw new Error('no draft');
			await api.updateAdminUser(editing.id, {
				display_name: draft.display_name.trim() || undefined,
				role: draft.role,
				is_active: draft.is_active,
			});
			return api.setUserGroups(editing.id, draft.group_ids);
		},
		onSuccess: () => {
			toast.success('已保存');
			setEditing(null);
			invalidate();
		},
		onError: (err) => toast.error(err.message),
	});

	// ---- 小组 ----
	const [groupName, setGroupName] = useState('');
	const [creating, setCreating] = useState(false);
	const createGroup = useMutation({
		mutationFn: () => api.createGroup(groupName.trim()),
		onSuccess: (g) => {
			toast.success(`已创建「${g.name}」`);
			setGroupName('');
			setCreating(false);
			invalidate();
		},
		onError: (err) => toast.error(err.message),
	});

	const [renaming, setRenaming] = useState<{ id: number; name: string } | null>(null);
	const renameGroup = useMutation({
		mutationFn: () => api.renameGroup(renaming!.id, renaming!.name.trim()),
		onSuccess: (g) => {
			toast.success(`已改名为「${g.name}」`);
			setRenaming(null);
			invalidate();
		},
		onError: (err) => toast.error(err.message),
	});

	const deleteGroup = useMutation({
		mutationFn: (id: number) => api.deleteGroup(id),
		onSuccess: () => {
			toast.success('已删除');
			invalidate();
		},
		onError: (err) => toast.error(err.message),
	});

	if (!isAdmin) {
		return (
			<div className="p-6">
				<p className="text-sm text-muted-foreground">组织管理仅管理员可见。</p>
			</div>
		);
	}

	return (
		<div className="h-full overflow-auto p-6">
			<div className="mx-auto max-w-5xl space-y-4">
				<div className="flex items-center gap-2.5">
					<span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
						<Users className="size-4.5" />
					</span>
					<div>
						<h1 className="text-lg font-semibold">组织管理</h1>
						<p className="text-xs text-muted-foreground">
							小组是知识库授权的载体：调整成员所在小组，即调整其可见的知识库范围。
						</p>
					</div>
				</div>

				<Card>
					<CardHeader>
						<CardTitle className="text-base">用户</CardTitle>
						<CardDescription>调整显示名、平台角色、启用状态与所属小组。</CardDescription>
					</CardHeader>
					<CardContent className="p-0">
						{users.isLoading ? (
							<p className="p-4 text-xs text-muted-foreground">加载中…</p>
						) : (
							<table className="w-full text-sm">
								<thead>
									<tr className="border-b text-left text-xs text-muted-foreground">
										<th className="px-3 py-2 font-medium">用户</th>
										<th className="px-3 py-2 font-medium">角色</th>
										<th className="px-3 py-2 font-medium">小组</th>
										<th className="px-3 py-2 font-medium">状态</th>
										<th className="px-3 py-2" />
									</tr>
								</thead>
								<tbody>
									{users.data?.map((u) => (
										<tr key={u.id} className="border-b last:border-0 hover:bg-row-hover">
											<td className="px-3 py-2">
												<span className="font-medium">{u.display_name || u.username}</span>
												<span className="ml-1.5 text-xs text-muted-foreground">@{u.username}</span>
											</td>
											<td className="px-3 py-2">
												<Badge variant={u.role === 'admin' ? 'default' : 'secondary'}>
													{u.role === 'admin' ? '管理员' : '成员'}
												</Badge>
											</td>
											<td className="px-3 py-2">
												{u.groups.length === 0 ? (
													<span className="text-xs text-muted-foreground">未分组</span>
												) : (
													<span className="text-xs">{u.groups.map((g) => g.name).join('、')}</span>
												)}
											</td>
											<td className="px-3 py-2">
												{u.is_active ? (
													<span className="text-xs text-muted-foreground">正常</span>
												) : (
													<Badge variant="destructive">已停用</Badge>
												)}
											</td>
											<td className="px-3 py-2 text-right">
												<Button
													size="sm"
													variant="outline"
													onClick={() => {
														setEditing(u);
														setDraft({
															display_name: u.display_name,
															role: u.role,
															is_active: u.is_active,
															group_ids: u.groups.map((g) => g.id),
														});
													}}
												>
													调整
												</Button>
											</td>
										</tr>
									))}
								</tbody>
							</table>
						)}
					</CardContent>
				</Card>

				<Card>
					<CardHeader className="flex-row items-center justify-between space-y-0">
						<div>
							<CardTitle className="text-base">小组</CardTitle>
							<CardDescription>
								有成员或挂着知识库授权的小组不能删除，先移走成员 / 解除授权。
							</CardDescription>
						</div>
						<Button size="sm" variant="outline" onClick={() => setCreating(!creating)}>
							<Plus className="size-4" /> 新建小组
						</Button>
					</CardHeader>
					<CardContent className="space-y-1.5">
						{creating && (
							<form
								className="flex items-center gap-2 rounded-lg border p-3"
								onSubmit={(e) => {
									e.preventDefault();
									if (groupName.trim()) createGroup.mutate();
								}}
							>
								<Input
									className="max-w-64"
									placeholder="小组名称"
									value={groupName}
									onChange={(e) => setGroupName(e.target.value)}
								/>
								<Button type="submit" size="sm" disabled={!groupName.trim() || createGroup.isPending}>
									{createGroup.isPending && <Loader2 className="size-4 animate-spin" />} 创建
								</Button>
							</form>
						)}
						{(groups.data ?? []).map((g) => {
							const memberCount = (users.data ?? []).filter((u) =>
								u.groups.some((ug) => ug.id === g.id),
							).length;
							return (
								<div
									key={g.id}
									className="flex items-center justify-between rounded-lg border px-3 py-2 text-sm"
								>
									<div className="flex items-center gap-3">
										<span className="font-medium">{g.name}</span>
										<span className="text-xs text-muted-foreground">{memberCount} 名成员</span>
									</div>
									<div className="flex items-center gap-1">
										<Button
											size="sm"
											variant="ghost"
											className="h-7 w-7 px-0"
											title="改名"
											onClick={() => setRenaming({ id: g.id, name: g.name })}
										>
											<Pencil className="size-3.5" />
										</Button>
										<Button
											size="sm"
											variant="ghost"
											className="h-7 w-7 px-0 text-destructive"
											title="删除"
											disabled={deleteGroup.isPending}
											onClick={() => deleteGroup.mutate(g.id)}
										>
											<X className="size-4" />
										</Button>
									</div>
								</div>
							);
						})}
					</CardContent>
				</Card>
			</div>

			{/* 用户调整对话框：显示名 / 角色 / 启用 / 小组一次提交 */}
			<Dialog open={editing !== null} onOpenChange={(open) => !open && setEditing(null)}>
				<DialogContent>
					<DialogHeader>
						<DialogTitle>调整用户{editing ? ` @${editing.username}` : ''}</DialogTitle>
						<DialogDescription>
							不能降级或停用自己的账号；小组勾选即替换全部所属关系。
						</DialogDescription>
					</DialogHeader>
					{draft && (
						<div className="space-y-3">
							<div className="space-y-1.5">
								<Label>显示名</Label>
								<Input
									value={draft.display_name}
									onChange={(e) => setDraft({ ...draft, display_name: e.target.value })}
								/>
							</div>
							<div className="flex items-center justify-between">
								<Label>平台角色</Label>
								<Select
									value={draft.role}
									onValueChange={(v) => setDraft({ ...draft, role: v as 'admin' | 'member' })}
								>
									<SelectTrigger className="w-32">
										<SelectValue />
									</SelectTrigger>
									<SelectContent>
										<SelectItem value="member">成员</SelectItem>
										<SelectItem value="admin">管理员</SelectItem>
									</SelectContent>
								</Select>
							</div>
							<div className="flex items-center justify-between">
								<Label>账号启用</Label>
								<Switch
									checked={draft.is_active}
									onCheckedChange={(v) => setDraft({ ...draft, is_active: v })}
								/>
							</div>
							<div className="space-y-1.5">
								<Label>所属小组</Label>
								<div className="space-y-2 rounded-lg border p-3">
									{(groups.data ?? []).map((g) => (
										<label key={g.id} className="flex cursor-pointer items-center gap-2 text-sm">
											<Checkbox
												checked={draft.group_ids.includes(g.id)}
												onCheckedChange={(v) =>
													setDraft({
														...draft,
														group_ids: v
															? [...draft.group_ids, g.id]
															: draft.group_ids.filter((id) => id !== g.id),
													})
												}
											/>
											{g.name}
										</label>
									))}
									{(groups.data ?? []).length === 0 && (
										<p className="text-xs text-muted-foreground">还没有小组，先在下方新建。</p>
									)}
								</div>
							</div>
						</div>
					)}
					<DialogFooter>
						<DialogClose asChild>
							<Button variant="outline">取消</Button>
						</DialogClose>
						<Button disabled={!draft || saveUser.isPending} onClick={() => saveUser.mutate()}>
							{saveUser.isPending && <Loader2 className="size-4 animate-spin" />} 保存
						</Button>
					</DialogFooter>
				</DialogContent>
			</Dialog>

			{/* 小组改名对话框 */}
			<Dialog open={renaming !== null} onOpenChange={(open) => !open && setRenaming(null)}>
				<DialogContent>
					<DialogHeader>
						<DialogTitle>小组改名</DialogTitle>
					</DialogHeader>
					{renaming && (
						<Input
							value={renaming.name}
							onChange={(e) => setRenaming({ ...renaming, name: e.target.value })}
						/>
					)}
					<DialogFooter>
						<DialogClose asChild>
							<Button variant="outline">取消</Button>
						</DialogClose>
						<Button
							disabled={!renaming?.name.trim() || renameGroup.isPending}
							onClick={() => renameGroup.mutate()}
						>
							{renameGroup.isPending && <Loader2 className="size-4 animate-spin" />} 保存
						</Button>
					</DialogFooter>
				</DialogContent>
			</Dialog>
		</div>
	);
}
