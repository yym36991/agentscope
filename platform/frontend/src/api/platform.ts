/**
 * L1 orchestration backend client (the ONLY backend this app talks to).
 *
 * All calls go through the Vite dev proxy `/api -> :8100` (rewritten to
 * strip the prefix), so in dev there is no CORS and no absolute URL. JWT
 * lives in localStorage; a 401 anywhere bumps the user to /login.
 */
import type { Msg, ToolCallBlock } from '@agentscope-ai/agentscope/message';

const BASE = '/api';
const TOKEN_KEY = 'platform_token';

export function getToken(): string | null {
	return localStorage.getItem(TOKEN_KEY);
}
export function setToken(token: string) {
	localStorage.setItem(TOKEN_KEY, token);
}
export function clearToken() {
	localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
	readonly status: number;
	readonly detail: string;
	constructor(status: number, detail: string) {
		super(detail);
		this.name = 'ApiError';
		this.status = status;
		this.detail = detail;
	}
}

async function request<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
	const headers: Record<string, string> = {};
	const token = getToken();
	if (token) headers['Authorization'] = `Bearer ${token}`;
	// FormData bodies keep the browser's multipart boundary header.
	if (body !== undefined && !(body instanceof FormData)) {
		headers['Content-Type'] = 'application/json';
	}
	const res = await fetch(`${BASE}${path}`, {
		method,
		headers,
		body:
			body === undefined
				? undefined
				: body instanceof FormData
					? body
					: JSON.stringify(body),
	});
	if (res.status === 401 && !path.startsWith('/auth/')) {
		clearToken();
		window.location.href = '/login';
		throw new ApiError(401, '登录已过期，请重新登录');
	}
	if (!res.ok) {
		let detail = res.statusText;
		try {
			const json = (await res.json()) as { detail?: unknown };
			if (typeof json.detail === 'string') detail = json.detail;
			else if (json.detail !== undefined) detail = JSON.stringify(json.detail);
		} catch {
			/* not JSON */
		}
		throw new ApiError(res.status, detail);
	}
	if (res.status === 204) return undefined as T;
	return (await res.json()) as T;
}

// ---------- types (mirror the L1 response models) ----------

export interface UserOut {
	id: number;
	username: string;
	groups: string[];
	role?: 'admin' | 'member';
}

export interface ProjectOut {
	id: number;
	name: string;
	status: string;
	current_stage: string;
	owner_user_id: number;
	created_at: string;
}

export interface StageRunOut {
	id: number;
	project_id: number;
	stage: string;
	status: string;
	round: number;
	session_id: string | null;
	created_at: string;
	/** 最新一次审批决定时间：甘特条右端点（未决定为 null） */
	decided_at?: string | null;
	warning?: string | null;
}

export interface ArtifactOut {
	id: number;
	version_no: number;
	title: string;
	format: string;
	storage_path: string;
}

export interface WorkspaceFileOut {
	path: string;
	name: string;
	size_bytes: number | null;
}

export interface ApprovalOut {
	id: number;
	stage_run_id: number;
	project_id: number;
	project_name: string;
	stage: string;
	run_round: number;
	run_status: string;
	status: string;
	comment: string | null;
}

export interface MemberOut {
	id: number;
	user_id: number;
	username: string;
	display_name: string;
	role: string;
	created_at: string;
}

export const ROLE_LABELS: Record<string, string> = {
	initiator: '发起人',
	manager: '项目经理',
	member: '成员',
	approver: '审批人',
	observer: '观察者',
};

export interface RemoveMemberOut {
	/** 移除时自动改道给负责人的在途待审任务数 */
	reassigned_tasks: number;
}

export interface MessagesOut {
	messages: Msg[];
	is_running: boolean;
	has_more: boolean;
	event_cursor: string | null;
}

export const STAGE_ORDER = [
	'requirement',
	'prototype',
	'budget',
	'testcases',
	'testing',
	'acceptance',
] as const;

export const STAGE_LABELS: Record<string, string> = {
	requirement: '需求生成',
	prototype: '原型设计',
	budget: '工时预算',
	testcases: '测试用例',
	testing: '测试',
	acceptance: '验收审计',
};

export const KB_TYPE_LABELS: Record<string, string> = {
	spec: '行业规范库',
	price: '价格基准库',
	case: '案例库',
	template: '模板库',
	distill: '沉淀库',
};

// ---------- knowledge bases (M3) ----------

export interface KbGrantOut {
	group_id: number;
	group_name: string;
	level: 'read' | 'write';
}

export interface KbOut {
	id: number;
	name: string;
	kb_type: 'spec' | 'price' | 'case' | 'template' | 'distill';
	description: string;
	/** null while no embedding credential is registered — KB stays a stub. */
	agentscope_kb_id: string | null;
	owner_group_id: number | null;
	/** admin-only projection */
	grants: KbGrantOut[] | null;
}

export interface KbDocOut {
	document_id: string;
	filename: string;
	status: string;
}

export interface KbSearchHit {
	content?: string;
	text?: string;
	score?: number;
	metadata?: Record<string, unknown>;
}

export interface KbLinkOut {
	id: number;
	kb_id: number;
	kb_name: string;
	kb_type: KbOut['kb_type'];
	stage: string | null;
}

export interface GroupOut {
	id: number;
	name: string;
}

export interface PriceItemOut {
	id: number;
	region: string;
	item_type: string;
	name: string;
	value: number;
	unit: string;
	effective_year: number;
	source: string;
	notes: string;
}

// ---------- 管理视图：统计看板 / 意见台账 / 组织管理 ----------

export const PROJECT_STATUS_LABELS: Record<string, string> = {
	draft: '草稿',
	active: '进行中',
	accepted: '已验收',
	archived: '已归档',
};

export interface StageStatOut {
	stage: string;
	runs: number;
	approved: number;
	returned: number;
	/** 首轮创建 → 审批决定的平均小时数（无已通过运行则 null） */
	avg_hours: number | null;
	avg_rounds: number | null;
	return_rate: number;
}

export interface StatsOut {
	projects_total: number;
	projects_by_status: Record<string, number>;
	stages: StageStatOut[];
	approvals: { approved: number; returned: number; pending: number };
	price: { items: number; regions: number; by_type: Record<string, number> };
}

export interface FeedbackOut {
	id: number;
	project_id: number;
	project_name: string | null;
	/** stage = 阶段审批意见，consolidation = 知识沉淀审阅意见 */
	kind: string;
	stage: string | null;
	run_round: number | null;
	action: 'approved' | 'returned';
	comment: string;
	approver: string;
	decided_at: string;
}

export interface AdminUserOut {
	id: number;
	username: string;
	display_name: string;
	role: 'admin' | 'member';
	is_active: boolean;
	groups: GroupOut[];
}

// ---------- 追溯矩阵（§7.3） ----------

export interface TraceReqRow {
	req_id: string;
	title: string;
	summary: string;
}

export interface TraceFpRow {
	fp_id: string;
	name: string;
	category: 'ILF' | 'EIF' | 'EI' | 'EO' | 'EQ';
	complexity: string | null;
	fr_refs: string[];
	/** NESMA 估算功能点法类别权重（L1 侧定价） */
	weight: number;
	hours: number | null;
}

export interface TraceTcRow {
	tc_id: string;
	title: string;
	fp_refs: string[];
}

export interface TraceOut {
	requirements: TraceReqRow[];
	function_points: TraceFpRow[];
	test_cases: TraceTcRow[];
	ufp: number;
	hours_total: number | null;
	/** stage → 产出该切片的最新已批准 run id */
	produced_at: Record<string, number>;
}

// ---------- resource hubs ----------

export interface HubInfo {
	hub_id: string;
	display_name: string;
	description: string;
	icon_url: string | null;
}

export interface HubCard {
	id: string;
	hub_id: string;
	name: string;
	description: string;
	tags?: string[];
	author?: string | null;
	icon_url?: string | null;
	installs?: number | null;
	/** MCP only: `inputs` means install needs a values form. */
	auth?: 'none' | 'inputs';
	inputs_schema?: { properties?: Record<string, { title?: string }> } | null;
	is_stateful?: boolean;
}

export interface McpLibItem {
	id: string;
	name: string;
	enabled: boolean;
	is_stateful: boolean;
	display_name: string | null;
	description: string;
	tags: string[];
}

export interface SkillLibItem {
	id: string;
	name: string;
	enabled: boolean;
	display_name: string | null;
	description: string;
	tags: string[];
}

// ---------- auth ----------

export const api = {
	login: (username: string, password?: string) =>
		request<{ access_token: string; token_type: string; user: UserOut }>(
			'/auth/login',
			'POST',
			password ? { username, password } : { username },
		),
	register: (username: string, password?: string, displayName?: string) =>
		request<UserOut>('/auth/register', 'POST', {
			username,
			...(password ? { password } : {}),
			...(displayName ? { display_name: displayName } : {}),
		}),
	me: () => request<UserOut>('/users/me'),

	// ---------- projects & stages ----------
	listProjects: () => request<ProjectOut[]>('/projects'),
	createProject: (name: string) => request<ProjectOut>('/projects', 'POST', { name }),
	getProject: (id: number) => request<ProjectOut>(`/projects/${id}`),
	listStageRuns: (projectId: number) => request<StageRunOut[]>(`/projects/${projectId}/stage-runs`),
	startStage: (projectId: number, stage: string) =>
		request<StageRunOut>(`/projects/${projectId}/stages/${stage}/start`, 'POST'),

	// ---------- stage-run conversation ----------
	chat: (runId: number, content: string) =>
		request<{ ok: boolean; session_id: string }>(`/stage-runs/${runId}/chat`, 'POST', { content }),
	uploadChat: (runId: number, file: File, text?: string) => {
		const form = new FormData();
		form.append('file', file);
		if (text) form.append('text', text);
		return request<{ ok: boolean; session_id: string; file: string }>(
			`/stage-runs/${runId}/chat-upload`,
			'POST',
			form,
		);
	},
	messages: (runId: number) => request<MessagesOut>(`/stage-runs/${runId}/messages`),
	confirm: (runId: number, confirmed: boolean, toolCallIds?: string[], allowAll?: boolean) =>
		request<{ ok: boolean; confirmed: boolean; tool_calls: string[]; allow_all_applied: boolean }>(
			`/stage-runs/${runId}/confirm`,
			'POST',
			{ confirmed, tool_call_ids: toolCallIds, allow_all: allowAll },
		),
	interrupt: (runId: number) =>
		request<{ ok: boolean; session_id: string }>(`/stage-runs/${runId}/interrupt`, 'POST'),

	// ---------- artifacts & approvals ----------
	listRunArtifacts: (runId: number) =>
		request<ArtifactOut[]>(`/stage-runs/${runId}/artifacts`),
	getRunArtifact: (runId: number, artifactId: number) =>
		request<ArtifactOut & { content: string }>(`/stage-runs/${runId}/artifacts/${artifactId}`),
	// Export renders server-side (md → docx/xlsx); the response is a
	// file blob, so it can't go through the JSON request() helper.
	exportRunArtifact: async (runId: number, artifactId: number, fmt: 'docx' | 'xlsx') => {
		const res = await fetch(
			`${BASE}/stage-runs/${runId}/artifacts/${artifactId}/export?fmt=${fmt}`,
			{ headers: { Authorization: `Bearer ${getToken()}` } },
		);
		if (!res.ok) {
			let detail = res.statusText;
			try {
				const json = (await res.json()) as { detail?: unknown };
				if (typeof json.detail === 'string') detail = json.detail;
			} catch {
				/* not JSON */
			}
			throw new ApiError(res.status, detail);
		}
		return res.blob();
	},
	submitLatest: (runId: number, title: string) =>
		request<ArtifactOut>(`/stage-runs/${runId}/submit-latest`, 'POST', { title }),
	listWorkspaceFiles: (runId: number) =>
		request<WorkspaceFileOut[]>(`/stage-runs/${runId}/workspace-files`),
	getWorkspaceFile: (runId: number, path: string) =>
		request<{ path: string; format: string; content: string }>(
			`/stage-runs/${runId}/workspace-file?path=${encodeURIComponent(path)}`,
		),
	submitFile: (runId: number, title: string, path: string) =>
		request<ArtifactOut>(`/stage-runs/${runId}/submit-file`, 'POST', { title, path }),
	pendingApprovals: () => request<ApprovalOut[]>('/approvals/pending'),
	decide: (taskId: number, action: 'approve' | 'return', comment?: string) =>
		request<{ task_id: number; action: string; run_status: string; project_stage: string; project_status: string }>(
			`/approvals/${taskId}/decide`,
			'POST',
			{ action, comment },
		),

	// ---------- project members ----------
	listMembers: (projectId: number) =>
		request<MemberOut[]>(`/projects/${projectId}/members`),
	addMember: (projectId: number, username: string, role: string) =>
		request<MemberOut>(`/projects/${projectId}/members`, 'POST', { username, role }),
	removeMember: (projectId: number, userId: number) =>
		request<RemoveMemberOut>(`/projects/${projectId}/members/${userId}`, 'DELETE'),

	// ---------- knowledge bases (M3: group-authorized, stage-bound) ----------
	listKbs: () => request<KbOut[]>('/kbs'),
	createKb: (name: string, kb_type: KbOut['kb_type'], description: string) =>
		request<KbOut>('/kbs', 'POST', { name, kb_type, description }),
	deleteKb: (kbId: number) => request<void>(`/kbs/${kbId}`, 'DELETE'),
	setKbGrants: (kbId: number, grants: { group_id: number; level: 'read' | 'write' }[]) =>
		request<KbOut>(`/kbs/${kbId}/grants`, 'PUT', { grants }),
	listKbDocs: (kbId: number) => request<KbDocOut[]>(`/kbs/${kbId}/documents`),
	uploadKbDoc: (kbId: number, file: File) => {
		const form = new FormData();
		form.append('file', file);
		return request<KbDocOut>(`/kbs/${kbId}/documents`, 'POST', form);
	},
	searchKb: (kbId: number, query: string, top_k = 5) =>
		request<{ results: KbSearchHit[] }>(`/kbs/${kbId}/search`, 'POST', { query, top_k }),
	listGroups: () => request<GroupOut[]>('/groups'),

	// ---------- project KB bindings ----------
	listKbLinks: (projectId: number) =>
		request<KbLinkOut[]>(`/projects/${projectId}/kb-links`),
	addKbLink: (projectId: number, kbId: number, stage: string | null) =>
		request<KbLinkOut>(`/projects/${projectId}/kb-links`, 'POST', {
			kb_id: kbId,
			stage,
		}),
	removeKbLink: (projectId: number, linkId: number) =>
		request<void>(`/projects/${projectId}/kb-links/${linkId}`, 'DELETE'),

	// ---------- price baseline (M3 structured track) ----------
	listPriceItems: (filters: { region?: string; item_type?: string; keyword?: string }) => {
		const q = new URLSearchParams();
		if (filters.region) q.set('region', filters.region);
		if (filters.item_type) q.set('item_type', filters.item_type);
		if (filters.keyword) q.set('keyword', filters.keyword);
		const qs = q.toString();
		return request<PriceItemOut[]>(`/price-items${qs ? `?${qs}` : ''}`);
	},
	importPriceItems: (file: File) => {
		const form = new FormData();
		form.append('file', file);
		return request<{ imported: number; replaced_regions: string[] }>(
			'/admin/price-items/import',
			'POST',
			form,
		);
	},

	// ---------- resource hubs (sys:runtime's shared library) ----------
	listMcpHubs: () => request<HubInfo[]>('/hubs/mcp'),
	listMcpCards: (hubId: string, params?: { q?: string; cursor?: string; limit?: number }) => {
		const q = new URLSearchParams();
		if (params?.q) q.set('q', params.q);
		if (params?.cursor) q.set('cursor', params.cursor);
		q.set('limit', String(params?.limit ?? 20));
		return request<{ cards: HubCard[]; next_cursor: string | null }>(
			`/hubs/mcp/${encodeURIComponent(hubId)}/cards?${q}`,
		);
	},
	installMcp: (hubId: string, cardId: string, name?: string, values?: Record<string, unknown>) =>
		request<McpLibItem>(
			`/hubs/mcp/${encodeURIComponent(hubId)}/cards/${encodeURIComponent(cardId)}/install`,
			'POST',
			{ name: name ?? null, values: values ?? {} },
		),
	listMcpLibrary: () => request<McpLibItem[]>('/mcp-library'),
	deleteMcp: (mcpId: string) => request<void>(`/mcp-library/${encodeURIComponent(mcpId)}`, 'DELETE'),
	updateMcp: (mcpId: string, patch: { enabled?: boolean; name?: string }) =>
		request<McpLibItem>(`/mcp-library/${encodeURIComponent(mcpId)}`, 'PATCH', patch),

	listSkillHubs: () => request<HubInfo[]>('/hubs/skill'),
	listSkillCards: (hubId: string, params?: { q?: string; cursor?: string; limit?: number }) => {
		const q = new URLSearchParams();
		if (params?.q) q.set('q', params.q);
		if (params?.cursor) q.set('cursor', params.cursor);
		q.set('limit', String(params?.limit ?? 20));
		return request<{ cards: HubCard[]; next_cursor: string | null }>(
			`/hubs/skill/${encodeURIComponent(hubId)}/cards?${q}`,
		);
	},
	installSkill: (hubId: string, cardId: string, name?: string) => {
		const q = name ? `?name=${encodeURIComponent(name)}` : '';
		return request<SkillLibItem>(
			`/hubs/skill/${encodeURIComponent(hubId)}/cards/${encodeURIComponent(cardId)}/install${q}`,
			'POST',
		);
	},
	listSkillLibrary: () => request<SkillLibItem[]>('/skill-library'),
	deleteSkill: (skillId: string) =>
		request<void>(`/skill-library/${encodeURIComponent(skillId)}`, 'DELETE'),

	// ---------- 管理视图 ----------
	getStats: () => request<StatsOut>('/stats'),
	listFeedback: (filters: { project_id?: number; action?: string; q?: string }) => {
		const q = new URLSearchParams();
		if (filters.project_id) q.set('project_id', String(filters.project_id));
		if (filters.action) q.set('action', filters.action);
		if (filters.q) q.set('q', filters.q);
		const qs = q.toString();
		return request<FeedbackOut[]>(`/feedback${qs ? `?${qs}` : ''}`);
	},
	listAdminUsers: () => request<AdminUserOut[]>('/admin/users'),
	updateAdminUser: (
		id: number,
		patch: { display_name?: string; role?: 'admin' | 'member'; is_active?: boolean },
	) => request<AdminUserOut>(`/admin/users/${id}`, 'PATCH', patch),
	setUserGroups: (id: number, groupIds: number[]) =>
		request<AdminUserOut>(`/admin/users/${id}/groups`, 'PUT', { group_ids: groupIds }),
	createGroup: (name: string) => request<GroupOut>('/groups', 'POST', { name }),
	renameGroup: (id: number, name: string) =>
		request<GroupOut>(`/groups/${id}`, 'PATCH', { name }),
	deleteGroup: (id: number) => request<void>(`/groups/${id}`, 'DELETE'),
	getTrace: (projectId: number) => request<TraceOut>(`/projects/${projectId}/trace`),
};

/** Asking tool calls of a message, for the HITL confirm bar. */
export function askingToolCalls(message: Msg | undefined): ToolCallBlock[] {
	if (!message || !Array.isArray(message.content)) return [];
	return message.content.filter(
		(b): b is ToolCallBlock =>
			b.type === 'tool_call' && (b as ToolCallBlock & { state?: string }).state === 'asking',
	);
}
