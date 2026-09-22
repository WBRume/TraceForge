"""Paginated library reads and immutable edits of diagnostic procedures."""
from copy import deepcopy
from uuid import uuid4
from sqlalchemy import String, cast, or_
from .models import PlaybookSpec, CasePlaybookLink, PlaybookRun
from .contracts import PlaybookError
from . import service


def page_specs(db, workspace_ids, *, page, page_size, keyword='', tags='', symptoms=''):
    query = db.query(PlaybookSpec).filter(PlaybookSpec.workspace_id.in_(workspace_ids))
    spec = PlaybookSpec.spec_json['spec']
    if keyword.strip():
        needle = '%' + keyword.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        query = query.filter(or_(PlaybookSpec.spec_key.ilike(needle, escape='\\'),
            spec['metadata']['title'].as_string().ilike(needle, escape='\\'),
            cast(spec['match']['symptoms'], String).ilike(needle, escape='\\')))
    if tags:
        query = query.filter(spec['metadata']['tags'].contains(tags))
    if symptoms:
        query = query.filter(spec['match']['symptoms'].contains(symptoms))
    total = query.count()
    rows = query.order_by(PlaybookSpec.created_at.desc(), PlaybookSpec.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    stats = {}
    for ws_id in {row.workspace_id for row in rows}:
        stats.update(service.spec_statistics(db, ws_id))
    return {'items': [{**service.serialize_spec(row), 'statistics': stats.get(row.id)} for row in rows],
            'page': page, 'page_size': page_size, 'total': total}


def get_spec(db, ws_id, spec_id):
    row = db.query(PlaybookSpec).filter_by(id=spec_id, workspace_id=ws_id).first()
    if not row:
        raise PlaybookError('SPEC_NOT_FOUND', status=404)
    return row


def detail(row):
    return {**service.serialize_spec(row), 'document': deepcopy(row.spec_json['spec'])}


def edit_spec(db, ws_id, spec_id, document):
    from .compiler import compile_spec
    original = get_spec(db, ws_id, spec_id)
    updated = deepcopy(compile_spec(document)['spec'])
    if updated['metadata']['id'] != original.spec_key:
        raise PlaybookError('SPEC_ID_IMMUTABLE', status=409)
    updated['metadata'].pop('sourceCaseRefs', None)
    context = updated.setdefault('context', {})
    if not isinstance(context, dict):
        raise PlaybookError('INVALID_ANALYSIS_CONTEXT')
    for key in ('source_cases', 'call_chain', 'promotion_job_id'):
        context.pop(key, None)
    updated['metadata']['version'] = 'edit-' + uuid4().hex[:24]
    row = service.register_spec(db, ws_id, updated)
    for link in db.query(CasePlaybookLink).filter_by(spec_id=original.id):
        db.add(CasePlaybookLink(case_id=link.case_id, spec_id=row.id, revision_json={
            'kind': 'PLAYBOOK_EDIT', 'previous_spec_id': original.id,
            'spec_candidate': deepcopy(row.spec_json['spec'])}))
    return detail(row)


def delete_spec(db, ws_id, spec_id):
    row = get_spec(db, ws_id, spec_id)
    db.query(CasePlaybookLink).filter_by(spec_id=row.id).update({CasePlaybookLink.spec_id: None})
    db.query(PlaybookRun).filter_by(spec_id=row.id).delete(synchronize_session=False)
    db.delete(row)
    return {'msg': 'Playbook deleted successfully', 'id': spec_id}

