"""Exact approved successor status route; never executes an arbitrary plan-selected program."""
from pathlib import Path
MODEL='HILEGA_WARMUP_PREVENTION_INSTALL_V1'
def status_driver(root,plan):
    expected=root/'hilega-warmup-prevention-deploy-v1/manage.py'
    if plan.get('model')!=MODEL or plan.get('repo')!=str(root) or plan.get('production_execution_enabled') is not False:
        raise ValueError('SUPPORTED_CLOSED_SUCCESSOR_PLAN_REQUIRED')
    if plan.get('status_driver')!=str(expected):raise ValueError('UNAPPROVED_STATUS_DRIVER')
    return expected
def validate_status(value):
    if value.get('phase')!='CLOSED_WARMUP_PREVENTION_RUNNING' or value.get('prevention_deployed') is not True or value.get('controller_resumed') is not False or value.get('production_execution_enabled') is not False:
        raise ValueError('CLOSED_WARMUP_SUCCESSOR_NOT_VERIFIED')
    return True
