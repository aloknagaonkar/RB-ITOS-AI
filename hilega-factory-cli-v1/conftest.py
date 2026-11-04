"""Scope the test interpreter to the verified runtime; deny every real network connection."""
import os,socket,sys
from pathlib import Path
import pytest

bundle=Path(os.environ['HILEGA_PACKAGE_B_BUNDLE']).resolve()
sys.path[:0]=[str(bundle/'backend'),str(bundle/'runtime'),str(Path(__file__).parent/'fixtures')]
import market_lab
assert Path(market_lab.__file__).resolve()==bundle/'backend/market_lab/__init__.py'
market_lab.__path__=[str(bundle/'backend/market_lab')]

@pytest.fixture(autouse=True)
def no_real_network(monkeypatch):
    def forbidden(*args,**kwargs):raise AssertionError('Real network forbidden in Package B synthetic tests')
    monkeypatch.setattr(socket.socket,'connect',forbidden)
    monkeypatch.setattr(socket,'create_connection',forbidden)
    monkeypatch.setattr(socket,'getaddrinfo',forbidden)
