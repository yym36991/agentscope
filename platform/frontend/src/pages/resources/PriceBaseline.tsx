import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Coins, Loader2, Search, Upload } from 'lucide-react';
import { useRef, useState } from 'react';
import { toast } from 'sonner';

import { api } from '@/api/platform';
import { useAuth } from '@/auth';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';

const ITEM_TYPE_HINTS = ['人月费率', '调整因子', '生产率基准'];

/**
 * 资源中心 · 价格基准（M3 结构化轨道）：预算智能体报价时通过
 * query_price_baseline 工具实时读取这里的数据，导入按
 * (region, effective_year) 整表替换。
 */
export function PriceBaselinePage() {
	const { user } = useAuth();
	const isAdmin = user?.role === 'admin';
	const queryClient = useQueryClient();

	const [draft, setDraft] = useState({ region: '', item_type: '', keyword: '' });
	const [filters, setFilters] = useState({ region: '', item_type: '', keyword: '' });
	const items = useQuery({
		queryKey: ['price-items', filters],
		queryFn: () => api.listPriceItems(filters),
	});

	const fileRef = useRef<HTMLInputElement>(null);
	const importItems = useMutation({
		mutationFn: (file: File) => api.importPriceItems(file),
		onSuccess: ({ imported, replaced_regions }) => {
			toast.success(
				`导入 ${imported} 条基准${replaced_regions.length ? `（整表替换：${replaced_regions.join('、')}）` : ''}`,
			);
			queryClient.invalidateQueries({ queryKey: ['price-items'] });
		},
		onError: (err) => toast.error(err.message),
	});

	return (
		<div className="h-full overflow-auto p-6">
			<div className="mx-auto max-w-5xl space-y-4">
				<div className="flex items-center justify-between gap-3">
					<div className="flex items-center gap-2.5">
						<span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
							<Coins className="size-4.5" />
						</span>
						<div>
							<h1 className="text-lg font-semibold">价格基准</h1>
							<p className="text-xs text-muted-foreground">
								预算智能体报价时通过工具实时读取这里的数据；导入按（地区 × 生效年份）整表替换。
							</p>
						</div>
					</div>
					{isAdmin && (
						<div>
							<input
								ref={fileRef}
								type="file"
								hidden
								accept=".csv,.xlsx"
								onChange={(e) => {
									const f = e.target.files?.[0];
									if (f) importItems.mutate(f);
									e.target.value = '';
								}}
							/>
							<Button size="sm" disabled={importItems.isPending} onClick={() => fileRef.current?.click()}>
								{importItems.isPending ? <Loader2 className="size-4 animate-spin" /> : <Upload className="size-4" />}
								导入 CSV / XLSX
							</Button>
						</div>
					)}
				</div>

				<form
					className="flex flex-wrap items-center gap-2"
					onSubmit={(e) => {
						e.preventDefault();
						setFilters({
							region: draft.region.trim(),
							item_type: draft.item_type.trim(),
							keyword: draft.keyword.trim(),
						});
					}}
				>
					<Input
						className="w-32"
						placeholder="地区，如 北京"
						value={draft.region}
						onChange={(e) => setDraft({ ...draft, region: e.target.value })}
					/>
					<Input
						className="w-32"
						list="price-item-types"
						placeholder="类型"
						value={draft.item_type}
						onChange={(e) => setDraft({ ...draft, item_type: e.target.value })}
					/>
					<datalist id="price-item-types">
						{ITEM_TYPE_HINTS.map((t) => (
							<option key={t} value={t} />
						))}
					</datalist>
					<Input
						className="w-44"
						placeholder="名称关键字"
						value={draft.keyword}
						onChange={(e) => setDraft({ ...draft, keyword: e.target.value })}
					/>
					<Button type="submit" size="sm" variant="outline">
						<Search className="size-4" /> 筛选
					</Button>
					{(filters.region || filters.item_type || filters.keyword) && (
						<Button
							type="button"
							size="sm"
							variant="ghost"
							onClick={() => {
								setDraft({ region: '', item_type: '', keyword: '' });
								setFilters({ region: '', item_type: '', keyword: '' });
							}}
						>
							清除
						</Button>
					)}
				</form>

				<Card>
					<CardContent className="p-0">
						{items.isLoading ? (
							<p className="p-4 text-xs text-muted-foreground">加载中…</p>
						) : items.data?.length === 0 ? (
							<p className="p-6 text-center text-xs text-muted-foreground">
								没有匹配的价格基准{isAdmin ? '，点右上角导入 CSV / XLSX。' : '。'}
							</p>
						) : (
							<table className="w-full text-sm">
								<thead>
									<tr className="border-b text-left text-xs text-muted-foreground">
										<th className="px-3 py-2 font-medium">地区</th>
										<th className="px-3 py-2 font-medium">类型</th>
										<th className="px-3 py-2 font-medium">名称</th>
										<th className="px-3 py-2 font-medium">基准值</th>
										<th className="px-3 py-2 font-medium">生效年份</th>
										<th className="px-3 py-2 font-medium">来源</th>
									</tr>
								</thead>
								<tbody>
									{items.data?.map((r) => (
										<tr key={r.id} className="border-b last:border-0 hover:bg-row-hover">
											<td className="px-3 py-2">{r.region}</td>
											<td className="px-3 py-2">{r.item_type}</td>
											<td className="px-3 py-2">
												{r.name}
												{r.notes && (
													<span className="ml-1 text-xs text-muted-foreground">（{r.notes}）</span>
												)}
											</td>
											<td className="px-3 py-2 whitespace-nowrap">
												{r.value.toLocaleString()} {r.unit}
											</td>
											<td className="px-3 py-2">{r.effective_year}</td>
											<td className="max-w-40 truncate px-3 py-2 text-xs text-muted-foreground" title={r.source}>
												{r.source}
											</td>
										</tr>
									))}
								</tbody>
							</table>
						)}
					</CardContent>
				</Card>

				<p className="text-xs leading-relaxed text-muted-foreground">
					导入文件表头（CSV 首行）需为：
					<code className="rounded bg-muted px-1 py-px font-mono">
						region,item_type,name,value,unit,effective_year,source,notes
					</code>
					；同一（地区， 生效年份）的旧数据会被整组替换，避免新旧基准混用。
				</p>
			</div>
		</div>
	);
}
