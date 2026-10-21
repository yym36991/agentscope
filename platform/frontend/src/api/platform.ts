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
	stage: string;
	run_status: string;
	status: string;
	comment: string | null;
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
	requirement: '需求分析',
	prototype: '原型设计',
	budget: '工时预算',
	testcases: '测试用例',
	testing: '测试',
	acceptance: '验收审计',
};

// ---------- auth ----------

export const api = {
	login: (username: string, password?: string) =>
		request<{ access_token: string; token_type: string; user: UserOut }>(
			'/auth/login',
			'POST',
			password ? { username, password } : { username },
		),
	register: (username: string, password?: string) =>
		request<UserOut>('/auth/register', 'POST', password ? { username, password } : { username }),
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

	// ---------- artifacts & approvals ----------
	listRunArtifacts: (runId: number) =>
		request<ArtifactOut[]>(`/stage-runs/${runId}/artifacts`),
	getRunArtifact: (runId: number, artifactId: number) =>
		request<ArtifactOut & { content: string }>(`/stage-runs/${runId}/artifacts/${artifactId}`),
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
};

/** Asking tool calls of a message, for the HITL confirm bar. */
export function askingToolCalls(message: Msg | undefined): ToolCallBlock[] {
	if (!message || !Array.isArray(message.content)) return [];
	return message.content.filter(
		(b): b is ToolCallBlock =>
			b.type === 'tool_call' && (b as ToolCallBlock & { state?: string }).state === 'asking',
	);
}
