"""A timed-out Windows launcher must not leave its native Python child alive."""
import os,sys,ctypes
from pathlib import Path
import pytest

@pytest.mark.skipif(sys.platform!='win32',reason='Windows venv process-tree regression')
def test_timeout_terminates_spawned_child(tmp_path,monkeypatch):
    from scripts import run_hackathon_1000_cascade as module
    monkeypatch.setattr(module,'_stage_env',lambda:dict(os.environ))
    marker=tmp_path/'child.pid'
    child=f"import os,time;from pathlib import Path;Path({str(marker)!r}).write_text(str(os.getpid()));time.sleep(30)"
    parent=f"import subprocess,sys,time;subprocess.Popen([sys.executable,'-c',{child!r}]);time.sleep(30)"
    rc,reason=module._run_stage([sys.executable,'-c',parent],tmp_path/'app.log',timeout=3)
    assert rc==124 and reason=='REGISTRATION_TIMEOUT:3'
    assert marker.exists(), 'Child must have started to verify tree cleanup'
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_bool,ctypes.c_ulong];kernel.OpenProcess.restype=ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_ulong];kernel.CloseHandle.argtypes=[ctypes.c_void_p]
    handle=kernel.OpenProcess(0x00100000,False,int(marker.read_text()))
    if handle:
        try:assert kernel.WaitForSingleObject(handle,0)==0
        finally:kernel.CloseHandle(handle)
