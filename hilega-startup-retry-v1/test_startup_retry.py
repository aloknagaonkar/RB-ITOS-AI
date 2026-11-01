import pytest
from startup_retry import wait_for_heartbeats


class Clock:
    def __init__(self):self.at=0
    def now(self):return self.at
    def pause(self,seconds):self.at+=seconds


def test_waits_for_delayed_initialization_and_two_distinct_heartbeats():
    c=Clock()
    def check():
        if c.at<3:raise ValueError('NEW_BRIDGE_HEARTBEAT_NOT_CURRENT')
    def read():return dict(phase='STARTING' if c.at<3 else 'RUNNING',heartbeat_at=1 if c.at<5 else 2,new_lease=c.at>=3)
    result=wait_for_heartbeats(check,read,lambda:True,clock=c.now,pause=c.pause)
    assert c.at==5 and result['heartbeat_advanced'] is True


def test_unchanging_heartbeat_times_out_even_when_first_check_passes():
    c=Clock()
    with pytest.raises(ValueError,match='BOUNDED_SOURCE_STARTUP_TIMEOUT'):
        wait_for_heartbeats(lambda:None,lambda:dict(heartbeat_at=1),lambda:True,timeout=4,clock=c.now,pause=c.pause)
    assert c.at==4


def test_new_worker_error_fails_without_waiting_full_timeout():
    c=Clock()
    def check():raise ValueError('SOURCE_WORKER_HEALTH_ERROR')
    with pytest.raises(ValueError,match='NEW_SOURCE_WORKER_REPORTED_ERROR_OR_STOPPED'):
        wait_for_heartbeats(check,lambda:dict(phase='ERROR',new_lease=True),lambda:True,clock=c.now,pause=c.pause)
    assert c.at==0


def test_paused_controller_check_is_not_relaxed():
    c=Clock()
    def check():raise ValueError('CONTROLLER_MUST_REMAIN_PAUSED')
    with pytest.raises(ValueError,match='CONTROLLER_MUST_REMAIN_PAUSED'):
        wait_for_heartbeats(check,lambda:None,lambda:True,clock=c.now,pause=c.pause)


def test_service_exit_fails_before_health_is_accepted():
    with pytest.raises(ValueError,match='MANAGED_SERVICE_EXITED_DURING_STARTUP'):
        wait_for_heartbeats(lambda:None,lambda:dict(heartbeat_at=1),lambda:False)


def test_old_lease_never_becomes_success_just_from_advancing_timestamp():
    c=Clock()
    def check():raise ValueError('NEW_BRIDGE_LEASE_REQUIRED')
    with pytest.raises(ValueError,match='BOUNDED_SOURCE_STARTUP_TIMEOUT'):
        wait_for_heartbeats(check,lambda:dict(phase='RUNNING',heartbeat_at=c.at,new_lease=False),lambda:True,timeout=3,clock=c.now,pause=c.pause)
