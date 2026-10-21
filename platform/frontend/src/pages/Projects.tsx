import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Loader2, Plus } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';

import { api, STAGE_LABELS } from '@/api/platform';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import {
	Dialog,
	DialogClose,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
	DialogTrigger,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

const STATUS_LABELS: Record<string, string> = {
	draft: '草稿',
	active: '进行中',
	accepted: '已验收',
	archived: '已归档',
	cancelled: '已取消',
};

/** 视图 A 入口：项目列表（类禅道仪表盘的最小版）。 */
export function ProjectsPage() {
	const queryClient = useQueryClient();
	const projects = useQuery({ queryKey: ['projects'], queryFn: api.listProjects });
	const [name, setName] = useState('');

	const create = useMutation({
		mutationFn: () => api.createProject(name.trim()),
		onSuccess: (p) => {
			toast.success(`项目「${p.name}」已创建`);
			setName('');
			queryClient.invalidateQueries({ queryKey: ['projects'] });
		},
		onError: (err) => toast.error(err.message),
	});

	return (
		<div className="h-full overflow-auto p-6">
			<div className="mx-auto max-w-4xl space-y-4">
				<div className="flex items-center justify-between">
					<h1 className="text-lg font-semibold">我的项目</h1>
					<Dialog>
						<DialogTrigger asChild>
							<Button size="sm">
								<Plus /> 新建项目
							</Button>
						</DialogTrigger>
						<DialogContent>
							<DialogHeader>
								<DialogTitle>新建项目</DialogTitle>
								<DialogDescription>
									创建后从「需求生成」阶段开始，六个阶段串行推进。
								</DialogDescription>
							</DialogHeader>
							<div className="space-y-2">
								<Label htmlFor="project-name">项目名称</Label>
								<Input
									id="project-name"
									value={name}
									onChange={(e) => setName(e.target.value)}
									placeholder="例如：信贷审批系统造价评估"
								/>
							</div>
							<DialogFooter>
								<DialogClose asChild>
									<Button variant="outline">取消</Button>
								</DialogClose>
								<DialogClose asChild>
									<Button
										disabled={!name.trim() || create.isPending}
										onClick={() => create.mutate()}
									>
										{create.isPending && <Loader2 className="animate-spin" />}
										创建
									</Button>
								</DialogClose>
							</DialogFooter>
						</DialogContent>
					</Dialog>
				</div>

				{projects.isLoading && <p className="text-sm text-muted-foreground">加载中…</p>}
				{projects.data?.length === 0 && (
					<Card>
						<CardContent className="py-10 text-center text-sm text-muted-foreground">
							还没有项目，点右上角「新建项目」开始。
						</CardContent>
					</Card>
				)}

				<div className="grid gap-3">
					{projects.data?.map((p) => (
						<Link key={p.id} to={`/projects/${p.id}`}>
							<Card className="py-4 transition-colors hover:bg-muted/50">
								<CardContent className="flex items-center justify-between px-4 py-0">
									<div>
										<div className="font-medium">{p.name}</div>
										<div className="mt-1 text-xs text-muted-foreground">
											当前阶段：{STAGE_LABELS[p.current_stage] ?? p.current_stage}
										</div>
									</div>
									<Badge variant={p.status === 'active' ? 'default' : 'secondary'}>
										{STATUS_LABELS[p.status] ?? p.status}
									</Badge>
								</CardContent>
							</Card>
						</Link>
					))}
				</div>
			</div>
		</div>
	);
}
