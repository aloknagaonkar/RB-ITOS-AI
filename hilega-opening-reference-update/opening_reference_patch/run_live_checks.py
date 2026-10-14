"""Six live adapter tests, excluding the unrelated optional sandbox bridge dependency."""
import ast,unittest
from pathlib import Path
p=Path('tests/test_hilega_alignment_dual_exit_live_v1.py')
tree=ast.parse(p.read_text())
tree.body=[n for n in tree.body if not (isinstance(n,ast.ImportFrom) and n.module=='market_lab.hilega_sandbox_event_bridge_v1') and not isinstance(n,ast.If)]
for n in tree.body:
 if isinstance(n,ast.ClassDef):n.body=[m for m in n.body if not (isinstance(m,ast.FunctionDef) and m.name=='test_bridge_strategy_isolation_order_and_idempotency')]
ns={'__name__':'focused_live_checks'};exec(compile(ast.fix_missing_locations(tree),str(p),'exec'),ns)
r=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ns['AlignmentLiveTests']))
raise SystemExit(0 if r.wasSuccessful() else 1)
