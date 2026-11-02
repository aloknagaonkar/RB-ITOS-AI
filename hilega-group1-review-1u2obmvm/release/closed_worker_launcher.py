"""Closed registered worker launcher. No execution factory activation."""
from pathlib import Path
import hashlib
import runpy
import sys
root=Path(__file__).resolve().parent
sys.path.insert(0,str(root/'backend'));sys.path.insert(0,str(root/'runtime'))
registration=root/'CLOSED-REGISTRATION.json'
sys.argv.extend(['--closed-registration',str(registration),'--closed-registration-sha256',hashlib.sha256(registration.read_bytes()).hexdigest()])
runpy.run_path(str(root/'scripts/hilega_production_simulator_bridge.py'),run_name='__main__')
