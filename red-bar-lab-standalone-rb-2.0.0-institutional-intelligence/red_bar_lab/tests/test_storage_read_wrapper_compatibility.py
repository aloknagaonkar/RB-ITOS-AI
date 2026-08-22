import inspect

from red_bar_lab.storage import RedBarDatabase


def _has_var_positional(callable_obj) -> bool:
    return any(
        parameter.kind is inspect.Parameter.VAR_POSITIONAL
        for parameter in inspect.signature(callable_obj).parameters.values()
    )


def test_truthful_score_read_wrappers_accept_positional_arguments():
    assert _has_var_positional(
        RedBarDatabase.read_institutional_execution_evaluations
    )
    assert _has_var_positional(RedBarDatabase.read_execution_queue)


def test_truthful_score_read_wrappers_continue_accepting_keywords(tmp_path):
    database = RedBarDatabase(tmp_path / "compatibility.sqlite")
    database.initialize()

    assert database.read_institutional_execution_evaluations(limit=5) == []
    assert database.read_execution_queue(limit=5) == []
