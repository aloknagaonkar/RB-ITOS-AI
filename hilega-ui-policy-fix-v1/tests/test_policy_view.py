import ast
import copy
from pathlib import Path
import os
import unittest

ROOT=Path(os.getenv('HILEGA_UI_CANDIDATE',str(Path(__file__).parents[1]/'files')))
path=ROOT/'backend/market_lab/hilega_directional_candle_ui_v1.py'
tree=ast.parse(path.read_text())
node=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='_policy_display_records')
scope={};exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec'),scope)
select=scope['_policy_display_records']


def row(version,status='PROCESSED',time='09:30'):
    return dict(stage='DIRECTIONAL_DECISION',status=status,payload=dict(
        decision_timestamp='2026-11-23T'+time+':00+05:30',
        strategy_id='HILEGA_V2_ALIGNMENT_DUAL_EXIT',decision_interval_minutes=3,
        strategy_version=version))


class PolicyViewTests(unittest.TestCase):
    def test_new_recovery_not_hidden_by_old_processed(self):
        old=row('old');new=row('new','RECOVERED')
        chosen,version,versions=select([old,new],'2026-11-23')
        self.assertEqual(chosen,[new]);self.assertEqual(version,'new')
        self.assertEqual(versions,['old','new'])

    def test_same_version_forward_priority_can_still_be_applied(self):
        rows=[row('new'),row('new','RECOVERED')]
        self.assertEqual(select(rows,'2026-11-23')[0],rows)

    def test_other_day_does_not_select_version(self):
        other=row('future');other['payload']['decision_timestamp']='2026-11-24T09:30:00+05:30'
        self.assertEqual(select([row('current'),other],'2026-11-23')[1],'current')

    def test_legacy_without_versions_is_unchanged(self):
        rows=[dict(stage='OTHER',payload={})]
        self.assertEqual(select(rows,'2026-11-23'),(rows,None,[]))

    def test_old_manual_reset_not_overlaid_on_new_policy(self):
        old=dict(stage='DIRECTIONAL_MANUAL_EXIT_RESET',payload=dict(strategy_version='old'))
        new=dict(stage='DIRECTIONAL_MANUAL_EXIT_RESET',payload=dict(strategy_version='new'))
        chosen,_,_=select([row('old'),old,row('new'),new],'2026-11-23')
        self.assertNotIn(old,chosen);self.assertIn(new,chosen)

    def test_input_records_are_not_mutated(self):
        rows=[row('old'),row('new','RECOVERED')];before=copy.deepcopy(rows)
        select(rows,'2026-11-23');self.assertEqual(rows,before)


if __name__=='__main__':unittest.main()
