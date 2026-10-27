"""Import verifiable source dates; do not invent earlier actors or stage dates."""
from django.db import migrations


def import_sources(apps, schema_editor):
    Event=apps.get_model('recruitment_experience','WorkflowEvent')
    Job=apps.get_model('recruitment','Recruitment')
    Candidate=apps.get_model('recruitment','Candidate')
    Interview=apps.get_model('recruitment','InterviewSchedule')
    User=apps.get_model('auth','User')
    Request=apps.get_model('recruitment_experience','Requisition')
    alias=schema_editor.connection.alias
    events=Event.objects.using(alias)
    for item in events.select_related('candidate','actor').all().iterator():
        actor=item.actor
        label=((actor.first_name+' '+actor.last_name).strip() or actor.username) if actor else 'Actor not recorded in original event'
        events.filter(pk=item.pk).update(job_id=item.candidate.recruitment_id_id if item.candidate_id else None,actor_label=label)
    def source(job_id,kind,detail,when,candidate_id=None,requisition_id=None,actor_id=None):
        if not when:return
        user=User.objects.using(alias).filter(pk=actor_id).first() if actor_id else None
        label=((user.first_name+' '+user.last_name).strip() or user.username) if user else 'Actor not recorded in source'
        row=events.create(job_id=job_id,candidate_id=candidate_id,requisition_id=requisition_id,kind=kind,detail=detail,origin='imported',actor_id=actor_id if user else None,actor_label=label,metadata={'source_date':when.isoformat()})
        events.filter(pk=row.pk).update(created_at=when)
    for job in Job.objects.using(alias).all().iterator():
        source(job.pk,'job_origin','Job created · original source record',job.created_at,actor_id=job.created_by_id)
    for candidate in Candidate.objects.using(alias).all().iterator():
        source(candidate.recruitment_id_id,'application_received','Application received · original source record',candidate.created_at,candidate.pk,actor_id=candidate.created_by_id)
    for appointment in Interview.objects.using(alias).select_related('candidate_id').all().iterator():
        if appointment.candidate_id_id:
            source(appointment.candidate_id.recruitment_id_id,'interview_source','Interview appointment record created · attendance is not inferred',appointment.created_at,appointment.candidate_id_id,actor_id=appointment.created_by_id)
    for req in Request.objects.using(alias).all().iterator():
        source(req.job_id,'requisition_origin','Manpower requisition submitted · original source record',req.created_at,requisition_id=req.pk,actor_id=req.requested_by_id)
        if req.decided_at:
            source(req.job_id,'requisition_decision','Requisition '+req.status+' · original decision',req.decided_at,requisition_id=req.pk,actor_id=req.approver_id)


class Migration(migrations.Migration):
    dependencies=[('recruitment_experience','0005_workflow_controls')]
    # Source history is intentionally retained if app code is rolled back. The
    # additive schema can stay in place alongside the previous app image.
    operations=[migrations.RunPython(import_sources,migrations.RunPython.noop)]
