import ast
from pathlib import Path
import sys
from unittest.mock import Mock
import pytest
import application_closed_hook_v2 as hook
import fixture_closed_worker as boundary

def original():
    return Path(hook.__file__).with_name("reviewed_application_worker_v2.txt").read_bytes()

def helper(monkeypatch):
    monkeypatch.setitem(sys.modules, "market_lab.hilega_closed_execution_boundary_v1", boundary)
    tree=ast.parse(hook.make_candidate(original()))
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="preparation_tick")
    scope={}
    exec(compile(ast.Module(body=[fn],type_ignores=[]),"<helper>","exec"),scope)
    return scope["preparation_tick"]

def test_exact_worker_hash():
    assert hook.digest(original())==hook.EXPECTED

def test_candidate_compiles_without_executing_main():
    compile(hook.make_candidate(original()),"<candidate>","exec")

def test_unrelated_top_level_functions_unchanged():
    before=ast.parse(original()); after=ast.parse(hook.make_candidate(original()))
    for node in before.body:
        if isinstance(node,ast.FunctionDef) and node.name!="main":
            other=next(n for n in after.body if isinstance(n,ast.FunctionDef) and n.name==node.name)
            assert ast.dump(node)==ast.dump(other)

def test_main_supplies_no_fixture_override():
    tree=ast.parse(hook.make_candidate(original()))
    main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="main")
    calls=[n for n in ast.walk(main) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=="preparation_tick"]
    assert len(calls)==1 and len(calls[0].args)==2 and not calls[0].keywords

def test_default_handoff_closed(monkeypatch):
    bridge=Mock(); bridge.run_source_once.return_value={"status":"PREPARED"}
    result=helper(monkeypatch)(bridge,"fixture.jsonl")
    bridge.run_source_once.assert_called_once_with("fixture.jsonl")
    assert result["execution_handoff"]["production_execution_enabled"] is False
    assert result["execution_handoff"]["application_database_opened"] is False

def test_preparation_failure_stops_handoff(monkeypatch):
    callback=Mock(side_effect=AssertionError("handoff must not run"))
    monkeypatch.setattr(boundary,"worker_tick",callback)
    bridge=Mock(); bridge.run_source_once.side_effect=ValueError("PREPARATION_FAILED")
    with pytest.raises(ValueError,match="PREPARATION_FAILED"):
        helper(monkeypatch)(bridge,"fixture.jsonl")
    callback.assert_not_called()

def test_changed_worker_rejected():
    with pytest.raises(ValueError,match="APPLICATION_WORKER_HASH_CHANGED"):
        hook.make_candidate(original()+b"\n# changed\n")

def test_inventory_does_not_export_arguments(tmp_path):
    script=tmp_path/"worker.py"; script.write_text("pass")
    result=hook.safe_unit("user","fixture.service",{"ExecStart":str(script)+" --token PRIVATE_SENTINEL", "Environment":"PRIVATE_SENTINEL"})
    assert result["script_paths"]==[str(script)]
    assert "PRIVATE_SENTINEL" not in str(result)
