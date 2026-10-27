# -*- coding: utf-8 -*-
"""Knowledge-base and price-baseline routes (architecture.md §7).

Group-level authorization lives here and ONLY here: the runtime KB
holds documents and vectors, while visibility, grants and project
bindings are platform facts. Every proxy endpoint (documents, search)
checks visibility before calling the runtime — filter first,
retrieve second (§7.2).
"""
import csv
import io
from typing import Annotated, Literal

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    UploadFile,
)
from pydantic import BaseModel, Field
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.projects import _get_project_or_404
from app.db import get_db
from app.models import (
    GrantLevel,
    Group,
    Kb,
    KbGrant,
    KbType,
    PlatformRole,
    PriceItem,
    ProjectKbLink,
    StageKey,
    User,
)
from app.runtime_client import (
    RuntimeCallError,
    get_runtime_client,
)

router = APIRouter(tags=["knowledge-bases"])

# Budget-stage uploads are xlsx lists; norms arrive as pdf/docx. The
# runtime parses anything it knows — the cap only guards the proxy.
_UPLOAD_LIMIT = 50 * 1024 * 1024


# ---------- schemas ----------

class KbCreateIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    kb_type: KbType
    description: str = Field(default="", max_length=2000)
    owner_group_id: int | None = None


class GrantIn(BaseModel):
    group_id: int
    level: Literal["read", "write"]


class GrantsIn(BaseModel):
    """Replace the KB's whole grant set in one call (idempotent)."""

    grants: list[GrantIn]


class GrantOut(BaseModel):
    group_id: int
    group_name: str
    level: GrantLevel


class KbOut(BaseModel):
    id: int
    name: str
    kb_type: KbType
    description: str
    agentscope_kb_id: str | None
    owner_group_id: int | None
    grants: list[GrantOut] | None = None  # admin-only projection


class KbDocOut(BaseModel):
    document_id: str
    filename: str
    status: str


class SearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)


class LinkIn(BaseModel):
    kb_id: int
    stage: StageKey | None = None  # None = bound to every stage


class LinkOut(BaseModel):
    id: int
    kb_id: int
    kb_name: str
    kb_type: KbType
    stage: StageKey | None


class PriceItemOut(BaseModel):
    id: int
    region: str
    item_type: str
    name: str
    value: float
    unit: str
    effective_year: int
    source: str
    notes: str

    model_config = {"from_attributes": True}


class PriceImportOut(BaseModel):
    imported: int
    replaced_regions: list[str]


# ---------- helpers ----------

class GroupOut(BaseModel):
    id: int
    name: str


@router.get("/groups", response_model=list[GroupOut])
async def list_groups(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[GroupOut]:
    """All groups, for the admin grants editor (users join groups
    themselves; the platform does not manage memberships yet)."""
    _require_admin(user)
    rows = await db.execute(select(Group).order_by(Group.name))
    return [GroupOut(id=g.id, name=g.name) for g in rows.scalars()]

def _require_admin(user: User) -> None:
    if user.role != PlatformRole.ADMIN:
        raise HTTPException(
            status_code=403, detail="platform admin role required"
        )


async def _visible_kb_ids(
    db: AsyncSession, user: User
) -> set[int] | None:
    """KB ids *user* may see; None = unrestricted (admin)."""
    if user.role == PlatformRole.ADMIN:
        return None
    group_ids = [g.id for g in user.groups]
    if not group_ids:
        return set()
    rows = await db.scalars(
        select(KbGrant.kb_id).where(KbGrant.group_id.in_(group_ids))
    )
    return set(rows)


async def _get_kb_or_403(
    db: AsyncSession, kb_id: int, user: User, write: bool = False
) -> Kb:
    """Fetch the KB, enforcing visibility (and write level) first."""
    kb = await db.get(Kb, kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail="knowledge base not found")
    visible = await _visible_kb_ids(db, user)
    if visible is not None and kb.id not in visible:
        raise HTTPException(status_code=403, detail="no grant for this knowledge base")
    if write and user.role != PlatformRole.ADMIN:
        group_ids = [g.id for g in user.groups]
        write_ok = await db.scalar(
            select(KbGrant.id).where(
                KbGrant.kb_id == kb.id,
                KbGrant.group_id.in_(group_ids),
                KbGrant.level == GrantLevel.WRITE,
            )
        )
        if write_ok is None:
            raise HTTPException(
                status_code=403, detail="write grant required for uploads"
            )
    return kb


def _flow_http(exc: RuntimeCallError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.detail)


async def _kb_out(db: AsyncSession, kb: Kb, user: User) -> KbOut:
    grants = None
    if user.role == PlatformRole.ADMIN:
        rows = (
            await db.execute(
                select(KbGrant, Group)
                .join(Group, KbGrant.group_id == Group.id)
                .where(KbGrant.kb_id == kb.id)
                .order_by(Group.name)
            )
        ).all()
        grants = [
            GrantOut(group_id=g.group_id, group_name=grp.name, level=g.level)
            for g, grp in rows
        ]
    return KbOut(
        id=kb.id,
        name=kb.name,
        kb_type=kb.kb_type,
        description=kb.description,
        agentscope_kb_id=kb.agentscope_kb_id,
        owner_group_id=kb.owner_group_id,
        grants=grants,
    )


# ---------- knowledge bases ----------

@router.get("/kbs", response_model=list[KbOut])
async def list_kbs(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[KbOut]:
    visible = await _visible_kb_ids(db, user)
    stmt = select(Kb).order_by(Kb.id)
    if visible is not None:
        if not visible:
            return []
        stmt = stmt.where(Kb.id.in_(visible))
    kbs = (await db.scalars(stmt)).all()
    return [await _kb_out(db, kb, user) for kb in kbs]


@router.post("/kbs", response_model=KbOut, status_code=201)
async def create_kb(
    payload: KbCreateIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> KbOut:
    """Admin: create a KB. The runtime KB is created first; if that
    fails (e.g. no embedding credential yet) nothing is persisted."""
    _require_admin(user)
    if await db.scalar(select(Kb.id).where(Kb.name == payload.name)):
        raise HTTPException(status_code=409, detail="name already taken")
    client = get_runtime_client()
    try:
        runtime_id = await client.create_kb(
            payload.name, payload.description
        )
    except RuntimeCallError as exc:
        raise _flow_http(exc) from exc
    kb = Kb(
        name=payload.name,
        kb_type=payload.kb_type,
        description=payload.description,
        agentscope_kb_id=runtime_id,
        owner_group_id=payload.owner_group_id,
    )
    db.add(kb)
    await db.commit()
    await db.refresh(kb)
    return await _kb_out(db, kb, user)


@router.delete("/kbs/{kb_id}", status_code=204)
async def delete_kb(
    kb_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Admin: drop the KB everywhere — runtime side first, then the
    grants/links rows cascade manually (no FK cascade configured)."""
    _require_admin(user)
    kb = await _get_kb_or_403(db, kb_id, user)
    client = get_runtime_client()
    try:
        if kb.agentscope_kb_id:
            await client.delete_kb(kb.agentscope_kb_id)
    except RuntimeCallError as exc:
        raise _flow_http(exc) from exc
    await db.execute(
        delete(KbGrant).where(KbGrant.kb_id == kb.id)
    )
    await db.execute(
        delete(ProjectKbLink).where(ProjectKbLink.kb_id == kb.id)
    )
    await db.delete(kb)
    await db.commit()


@router.put("/kbs/{kb_id}/grants", response_model=KbOut)
async def set_grants(
    kb_id: int,
    payload: GrantsIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> KbOut:
    """Admin: replace the grant set. Granting a group read+write on
    the same KB keeps only write (write implies read)."""
    _require_admin(user)
    kb = await _get_kb_or_403(db, kb_id, user)
    group_ids = {g.group_id for g in payload.grants}
    if group_ids:
        known = set(
            await db.scalars(
                select(Group.id).where(Group.id.in_(group_ids))
            )
        )
        missing = group_ids - known
        if missing:
            raise HTTPException(
                status_code=404,
                detail=f"unknown group ids: {sorted(missing)}",
            )
    await db.execute(delete(KbGrant).where(KbGrant.kb_id == kb.id))
    for g in payload.grants:
        db.add(
            KbGrant(
                kb_id=kb.id,
                group_id=g.group_id,
                level=GrantLevel.WRITE if g.level == "write" else GrantLevel.READ,
            )
        )
    await db.commit()
    await db.refresh(kb)
    return await _kb_out(db, kb, user)


@router.get("/kbs/{kb_id}/documents", response_model=list[KbDocOut])
async def list_kb_documents(
    kb_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[KbDocOut]:
    kb = await _get_kb_or_403(db, kb_id, user)
    if not kb.agentscope_kb_id:
        return []
    client = get_runtime_client()
    try:
        docs = await client.list_kb_documents(kb.agentscope_kb_id)
        status = {
            d.get("id") or d.get("document_id"): d.get("status")
            for d in await client.kb_document_status(kb.agentscope_kb_id)
        }
    except RuntimeCallError as exc:
        raise _flow_http(exc) from exc
    out = []
    for d in docs:
        did = d.get("id") or d.get("document_id")
        out.append(
            KbDocOut(
                document_id=did,
                filename=d.get("filename", ""),
                status=status.get(did, d.get("status", "unknown")),
            )
        )
    return out


@router.post("/kbs/{kb_id}/documents", response_model=KbDocOut, status_code=201)
async def upload_kb_document(
    kb_id: int,
    file: Annotated[UploadFile, File()],
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> KbDocOut:
    """Upload a document for indexing. Admins and write-granted group
    members; indexing itself runs async on the runtime."""
    kb = await _get_kb_or_403(db, kb_id, user, write=True)
    if not kb.agentscope_kb_id:
        raise HTTPException(
            status_code=409, detail="KB has no runtime counterpart"
        )
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=415, detail="文件为空")
    if len(raw) > _UPLOAD_LIMIT:
        raise HTTPException(
            status_code=413,
            detail=f"文件超过 {_UPLOAD_LIMIT // (1024 * 1024)}MB 上限",
        )
    client = get_runtime_client()
    try:
        result = await client.upload_kb_document(
            kb.agentscope_kb_id,
            file.filename or "uploaded.bin",
            raw,
            file.content_type,
        )
    except RuntimeCallError as exc:
        raise _flow_http(exc) from exc
    return KbDocOut(
        document_id=result["document_id"],
        filename=result["filename"],
        status=result["status"],
    )


@router.post("/kbs/{kb_id}/search")
async def search_kb(
    kb_id: int,
    payload: SearchIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    kb = await _get_kb_or_403(db, kb_id, user)
    if not kb.agentscope_kb_id:
        return {"results": []}
    client = get_runtime_client()
    try:
        results = await client.search_kb(
            kb.agentscope_kb_id, payload.query, payload.top_k
        )
    except RuntimeCallError as exc:
        raise _flow_http(exc) from exc
    return {"results": results}


# ---------- project KB links ----------

@router.get(
    "/projects/{project_id}/kb-links", response_model=list[LinkOut]
)
async def list_kb_links(
    project_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[LinkOut]:
    await _get_project_or_404(db, project_id, user)
    rows = (
        await db.execute(
            select(ProjectKbLink, Kb)
            .join(Kb, ProjectKbLink.kb_id == Kb.id)
            .where(ProjectKbLink.project_id == project_id)
            .order_by(ProjectKbLink.id)
        )
    ).all()
    return [
        LinkOut(
            id=link.id,
            kb_id=kb.id,
            kb_name=kb.name,
            kb_type=kb.kb_type,
            stage=link.stage,
        )
        for link, kb in rows
    ]


@router.post(
    "/projects/{project_id}/kb-links", response_model=LinkOut, status_code=201
)
async def add_kb_link(
    project_id: int,
    payload: LinkIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LinkOut:
    """Owner-only: bind a KB to the project, optionally to one stage.
    The bound KB need not be visible to the owner — visibility is
    checked per sender when the session mounts it (§7.2), so an
    invisible binding simply never activates for that person."""
    project = await _get_project_or_404(db, project_id, user)
    if project.owner_user_id != user.id and user.role != PlatformRole.ADMIN:
        raise HTTPException(
            status_code=403, detail="only the project owner can bind KBs"
        )
    kb = await db.get(Kb, payload.kb_id)
    if kb is None:
        raise HTTPException(status_code=404, detail="knowledge base not found")
    exists = await db.scalar(
        select(ProjectKbLink.id).where(
            ProjectKbLink.project_id == project_id,
            ProjectKbLink.kb_id == kb.id,
            ProjectKbLink.stage == payload.stage,
        )
    )
    if exists is not None:
        raise HTTPException(status_code=409, detail="link already exists")
    link = ProjectKbLink(
        project_id=project_id, kb_id=kb.id, stage=payload.stage
    )
    db.add(link)
    await db.commit()
    await db.refresh(link)
    return LinkOut(
        id=link.id,
        kb_id=kb.id,
        kb_name=kb.name,
        kb_type=kb.kb_type,
        stage=link.stage,
    )


@router.delete(
    "/projects/{project_id}/kb-links/{link_id}", status_code=204
)
async def remove_kb_link(
    project_id: int,
    link_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    project = await _get_project_or_404(db, project_id, user)
    if project.owner_user_id != user.id and user.role != PlatformRole.ADMIN:
        raise HTTPException(
            status_code=403, detail="only the project owner can bind KBs"
        )
    link = await db.get(ProjectKbLink, link_id)
    if link is None or link.project_id != project_id:
        raise HTTPException(status_code=404, detail="link not found")
    await db.delete(link)
    await db.commit()


# ---------- price baseline (§7.1 structured track) ----------

# CSV/XLSX import header — English keys, stable for scripts.
_PRICE_HEADERS = [
    "region",
    "item_type",
    "name",
    "value",
    "unit",
    "effective_year",
    "source",
    "notes",
]


@router.get("/price-items", response_model=list[PriceItemOut])
async def list_price_items(
    region: str | None = None,
    item_type: str | None = None,
    keyword: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PriceItemOut]:
    stmt = select(PriceItem).order_by(
        PriceItem.effective_year.desc(), PriceItem.id
    )
    if region:
        stmt = stmt.where(PriceItem.region == region)
    if item_type:
        stmt = stmt.where(PriceItem.item_type == item_type)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(
            or_(PriceItem.name.like(like), PriceItem.notes.like(like))
        )
    rows = (await db.scalars(stmt.limit(200))).all()
    return [PriceItemOut.model_validate(r) for r in rows]


@router.post("/admin/price-items/import", response_model=PriceImportOut)
async def import_price_items(
    file: Annotated[UploadFile, File()],
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PriceImportOut:
    """Admin: import the price baseline from CSV or XLSX.

    Header row (exact keys): region,item_type,name,value,unit,
    effective_year,source,notes. Importing a file replaces the rows of
    every (region, effective_year) combination the file contains —
    the file is the truth for those keys.
    """
    _require_admin(user)
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=415, detail="文件为空")
    name = file.filename or ""
    if name.lower().endswith(".csv"):
        text = raw.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        rows = [dict(r) for r in reader]
    elif name.lower().endswith(".xlsx"):
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        ws = wb.active
        grid = [list(r) for r in ws.iter_rows(values_only=True)]
        if not grid:
            raise HTTPException(status_code=415, detail="工作表为空")
        header = [str(h).strip() if h is not None else "" for h in grid[0]]
        rows = [
            {header[i]: c for i, c in enumerate(r) if i < len(header)}
            for r in grid[1:]
        ]
    else:
        raise HTTPException(
            status_code=415, detail="仅支持 .csv 或 .xlsx"
        )

    items: list[PriceItem] = []
    touched: set[tuple[str, int]] = set()
    for i, row in enumerate(rows, start=2):
        missing = [h for h in _PRICE_HEADERS[:6] if not str(row.get(h) or "").strip()]
        if missing:
            raise HTTPException(
                status_code=422,
                detail=f"第 {i} 行缺少必填列 {missing}（表头须为 "
                f"{','.join(_PRICE_HEADERS)}）",
            )
        try:
            value = float(str(row["value"]).replace(",", ""))
            year = int(str(row["effective_year"]).replace(",", ""))
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"第 {i} 行 value/effective_year 不是数字",
            ) from exc
        region = str(row["region"]).strip()
        touched.add((region, year))
        items.append(
            PriceItem(
                region=region,
                item_type=str(row["item_type"]).strip(),
                name=str(row["name"]).strip(),
                value=value,
                unit=str(row["unit"]).strip(),
                effective_year=year,
                source=str(row.get("source") or "").strip(),
                notes=str(row.get("notes") or "").strip(),
                imported_by_user_id=user.id,
            )
        )
    if not items:
        raise HTTPException(status_code=415, detail="没有数据行")

    for region, year in touched:
        await db.execute(
            delete(PriceItem).where(
                PriceItem.region == region,
                PriceItem.effective_year == year,
            )
        )
    db.add_all(items)
    await db.commit()
    return PriceImportOut(
        imported=len(items),
        replaced_regions=sorted({f"{r}/{y}" for r, y in touched}),
    )
