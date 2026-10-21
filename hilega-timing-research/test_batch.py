import unittest
import batch

class Checks(unittest.TestCase):
    def test_sessions_exclude_anchor(self):
        warm=[('2026-10-15',[1]),('2026-10-16',[1]),('2026-10-19',[1]),('2026-10-21',[1])]
        self.assertEqual(batch.select_sessions(warm,'2026-10-21',2),['2026-10-16','2026-10-19'])
    def test_empty_sessions_excluded(self):
        self.assertEqual(batch.select_sessions([('2026-10-15',[1]),('2026-10-16',[])],'2026-10-21',1),['2026-10-15'])
    def test_coverage_fails_closed(self):
        with self.assertRaisesRegex(ValueError,'INSUFFICIENT'):
            batch.select_sessions([('2026-10-15',[1])],'2026-10-21',2)
    def test_drawdown_uses_chronological_losses(self):
        trades=[dict(exit_time='2026-10-01T10:00',points=100),dict(exit_time='2026-10-01T11:00',points=-30),
            dict(exit_time='2026-10-01T12:00',points=-20),dict(exit_time='2026-10-01T13:00',points=60)]
        s=batch.stats(trades)
        self.assertEqual(s['net_points'],110);self.assertEqual(s['closed_trade_drawdown'],50)
        self.assertEqual(s['winning_points'],160);self.assertEqual(s['losing_points'],-50)
    def test_insufficient_audit_horizon_rejected(self):
        result=dict(trades=[],open_trade=None,audit=[])
        proof=batch.core.parity(result,[],batch.datetime.fromisoformat('2026-10-21T14:55:00+05:30'))
        self.assertEqual(proof['status'],'FAIL')
    def test_three_minute_reason_duration(self):
        p,l=batch.core.isolated_three()
        import inspect
        self.assertIn('timedelta(minutes=3)',inspect.getsource(p.followup_check))
        self.assertNotIn('timedelta(minutes=5)',inspect.getsource(p.followup_check))

if __name__=='__main__':unittest.main(verbosity=2)
