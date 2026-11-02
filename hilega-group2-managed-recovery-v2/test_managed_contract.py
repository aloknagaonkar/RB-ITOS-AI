import uuid
import pytest
from managed_arm import unit_arg
from managed_guard import recover

def test_systemd_paths_are_quoted():assert unit_arg('/tmp/a b')=='"/tmp/a b"'
def test_systemd_specifier_rejected():
    with pytest.raises(ValueError):unit_arg('/tmp/%x')
def test_newline_rejected():
    with pytest.raises(ValueError):unit_arg('/tmp/a\nb')
def test_recovery_uses_uuid_and_verifies_pause():
    class Store:
        mode='ARMED'
        def control(self):return dict(mode=self.mode,version=4,session_date='2026-11-02')
    class Service:
        store=Store()
        def command(self,action,**kw):
            assert action=='pause';uuid.UUID(kw['request_id']);self.store.mode='PAUSED'
    recover(Service())


def test_user_bus_environment_requires_owned_socket(tmp_path):
    import socket
    from managed_arm import user_bus_environment
    tmp_path.chmod(0o700)
    sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
    try:
        sock.bind(str(tmp_path/'bus'))
        env=user_bus_environment(tmp_path)
        assert env['XDG_RUNTIME_DIR']==str(tmp_path)
        assert env['DBUS_SESSION_BUS_ADDRESS']=='unix:path='+str(tmp_path/'bus')
    finally:sock.close()

def test_user_bus_regular_file_rejected(tmp_path):
    from managed_arm import user_bus_environment
    tmp_path.chmod(0o700);(tmp_path/'bus').write_text('not a socket')
    with pytest.raises(ValueError,match='OWNED_USER_SESSION_BUS_REQUIRED'):user_bus_environment(tmp_path)
