from copy import deepcopy
from datetime import datetime, timedelta
import unittest
from hilega_daily_loss_review_v1 import review, POLICY, ReviewBlocked

class Tests(unittest.TestCase):
    def setUp(self):
        self.now=datetime.fromisoformat('2026-10-29T11:00:00+05:30')
        self.config=dict(account_scope='fixture-account',session_date='2026-10-29',
            loss_accounting_policy=POLICY,policy_approved=True,daily_loss_limit_paise=100000,
            max_entry_cost_paise=50000,max_pnl_age_seconds=30)
        self.evidence=dict(account_scope='fixture-account',session_date='2026-10-29',
            pnl_attribution_verified=True,fees_complete=True,positions_reconciled=True,
            requests_reconciled=True,daily_stop_latched=False,open_position_count=0,
            pending_request_count=0,unresolved_outcome=False,observed_at=self.now.isoformat(),
            realized_net_pnl_paise=-10000,open_net_pnl_paise=-5000)
        self.candidate=dict(account_scope='fixture-account',session_date='2026-10-29',
            transaction_type='BUY',instrument_type='CE',pricing_policy_approved=True,
            cost_includes_fees=True,max_loss_cost_paise=20000)
    def run_review(self):
        return review(self.config,self.evidence,self.candidate,as_of=self.now,expected_account_scope='fixture-account')
    def test_good_values_are_review_only(self):
        value=self.run_review();self.assertEqual(value['status'],'REVIEWED_ONLY')
        self.assertEqual(value['conservative_loss_used_paise'],15000)
        self.assertEqual(value['remaining_loss_budget_paise'],85000)
        for k in ('entry_permission','production_ready','production_execution_enabled','orders_sent','evidence_authenticated_by_this_module','durable_daily_stop_latch_persisted'):
            self.assertIs(value[k],False)
    def test_missing_daily_limit_blocks(self):
        self.config['daily_loss_limit_paise']=None
        self.assertIn('DAILY_LOSS_LIMIT_MISSING',self.run_review()['reasons'])
    def test_unknown_pnl_not_assumed_zero(self):
        self.evidence['realized_net_pnl_paise']=None
        value=self.run_review();self.assertIn('REALIZED_PNL_UNAVAILABLE',value['reasons'])
        self.assertIsNone(value['conservative_loss_used_paise']);self.assertIsNone(value['remaining_loss_budget_paise'])
    def test_unverified_pnl_blocks_despite_arithmetic(self):
        self.evidence['pnl_attribution_verified']=False
        self.assertIn('PNL_ATTRIBUTION_UNVERIFIED',self.run_review()['reasons'])
    def test_fees_incomplete_blocks(self):
        self.evidence['fees_complete']=False
        self.assertIn('FEES_INCOMPLETE_OR_UNKNOWN',self.run_review()['reasons'])
    def test_unapproved_policy_blocks(self):
        self.config['policy_approved']=False
        self.assertIn('DAILY_LOSS_POLICY_UNAPPROVED',self.run_review()['reasons'])
    def test_unsupported_policy_blocks(self):
        self.config['loss_accounting_policy']='offset-profits'
        self.assertIn('LOSS_ACCOUNTING_POLICY_UNSUPPORTED',self.run_review()['reasons'])
    def test_realized_profit_does_not_offset_open_loss(self):
        self.evidence.update(realized_net_pnl_paise=50000,open_net_pnl_paise=-20000)
        self.assertEqual(self.run_review()['conservative_loss_used_paise'],20000)
    def test_open_profit_does_not_offset_realized_loss(self):
        self.evidence.update(realized_net_pnl_paise=-50000,open_net_pnl_paise=20000)
        self.assertEqual(self.run_review()['conservative_loss_used_paise'],50000)
    def test_profits_do_not_expand_budget(self):
        self.evidence.update(realized_net_pnl_paise=50000,open_net_pnl_paise=20000)
        self.assertEqual(self.run_review()['remaining_loss_budget_paise'],100000)
    def test_exact_loss_limit_blocks_and_requires_latch(self):
        self.evidence.update(realized_net_pnl_paise=-100000,open_net_pnl_paise=0)
        value=self.run_review();self.assertIn('DAILY_LOSS_LIMIT_REACHED',value['reasons'])
        self.assertTrue(value['daily_stop_latch_required']);self.assertFalse(value['durable_daily_stop_latch_persisted'])
    def test_over_limit_remaining_never_negative(self):
        self.evidence.update(realized_net_pnl_paise=-200000,open_net_pnl_paise=0)
        self.assertEqual(self.run_review()['remaining_loss_budget_paise'],0)
    def test_candidate_exceeds_remaining_budget(self):
        self.evidence.update(realized_net_pnl_paise=-90000,open_net_pnl_paise=0)
        self.assertIn('REMAINING_LOSS_BUDGET_EXCEEDED',self.run_review()['reasons'])
    def test_exact_remaining_budget_boundary(self):
        self.evidence.update(realized_net_pnl_paise=-80000,open_net_pnl_paise=0)
        self.assertEqual(self.run_review()['status'],'REVIEWED_ONLY')
    def test_max_entry_cost_blocks(self):
        self.candidate['max_loss_cost_paise']=50001
        self.assertIn('MAX_ENTRY_COST_EXCEEDED',self.run_review()['reasons'])
    def test_existing_latch_does_not_clear_when_pnl_recovers(self):
        self.evidence.update(daily_stop_latched=True,realized_net_pnl_paise=100000,open_net_pnl_paise=0)
        self.assertIn('DAILY_STOP_ALREADY_LATCHED',self.run_review()['reasons'])
    def test_unknown_latch_blocks(self):
        del self.evidence['daily_stop_latched']
        self.assertIn('DAILY_STOP_LATCH_STATE_UNKNOWN',self.run_review()['reasons'])
    def test_existing_position_blocks(self):
        self.evidence['open_position_count']=1
        self.assertIn('POSITION_ALREADY_OPEN',self.run_review()['reasons'])
    def test_pending_request_blocks(self):
        self.evidence['pending_request_count']=1
        self.assertIn('REQUEST_PENDING',self.run_review()['reasons'])
    def test_unknown_outcome_blocks(self):
        self.evidence['unresolved_outcome']=True
        self.assertIn('UNRESOLVED_EXECUTION_OUTCOME',self.run_review()['reasons'])
    def test_scope_mismatch_blocks_for_each_input(self):
        for target,prefix in ((self.config,'CONFIG'),(self.evidence,'EVIDENCE'),(self.candidate,'CANDIDATE')):
            target['account_scope']='other'
            self.assertIn(prefix+'_ACCOUNT_SCOPE_MISMATCH',self.run_review()['reasons'])
            target['account_scope']='fixture-account'
    def test_prior_session_blocks(self):
        self.evidence['session_date']='2026-10-28'
        self.assertIn('EVIDENCE_SESSION_MISMATCH',self.run_review()['reasons'])
    def test_stale_pnl_blocks(self):
        self.evidence['observed_at']=(self.now-timedelta(seconds=31)).isoformat()
        self.assertIn('PNL_OBSERVATION_STALE',self.run_review()['reasons'])
    def test_exact_age_boundary(self):
        self.evidence['observed_at']=(self.now-timedelta(seconds=30)).isoformat()
        self.assertEqual(self.run_review()['status'],'REVIEWED_ONLY')
    def test_future_pnl_blocks(self):
        self.evidence['observed_at']=(self.now+timedelta(seconds=1)).isoformat()
        self.assertIn('PNL_OBSERVATION_FUTURE',self.run_review()['reasons'])
    def test_boolean_money_rejected(self):
        self.config['daily_loss_limit_paise']=True
        with self.assertRaises(ReviewBlocked):self.run_review()
    def test_noninteger_money_rejected(self):
        for bad in ('1000',1000.0,float('nan'),float('inf')):
            self.candidate['max_loss_cost_paise']=bad
            with self.assertRaises(ReviewBlocked):self.run_review()
    def test_signed_loss_pnl_accepts_only_integers(self):
        self.evidence['realized_net_pnl_paise']=False
        with self.assertRaises(ReviewBlocked):self.run_review()
    def test_zero_daily_limit_rejected(self):
        self.config['daily_loss_limit_paise']=0
        with self.assertRaises(ReviewBlocked):self.run_review()
    def test_nonpositive_candidate_cost_rejected(self):
        for value in (0,-1):
            self.candidate['max_loss_cost_paise']=value
            with self.assertRaises(ReviewBlocked):self.run_review()
    def test_naive_pnl_time_rejected(self):
        self.evidence['observed_at']='2026-10-29T11:00:00'
        with self.assertRaises(ReviewBlocked):self.run_review()
    def test_naive_asof_rejected(self):
        self.now=self.now.replace(tzinfo=None)
        with self.assertRaises(ReviewBlocked):self.run_review()
    def test_missing_expected_account_rejected(self):
        with self.assertRaises(ReviewBlocked):review(self.config,self.evidence,self.candidate,as_of=self.now,expected_account_scope='')
    def test_age_limit_cannot_be_relaxed_beyond_scope(self):
        self.config['max_pnl_age_seconds']=31
        with self.assertRaises(ReviewBlocked):self.run_review()
    def test_sell_or_nonoption_cannot_use_preview(self):
        self.candidate['transaction_type']='SELL'
        self.assertIn('CANDIDATE_OUTSIDE_BUY_OPTION_SCOPE',self.run_review()['reasons'])
    def test_pricing_approval_required(self):
        self.candidate['pricing_policy_approved']=False
        self.assertIn('CANDIDATE_PRICING_UNAPPROVED',self.run_review()['reasons'])
    def test_candidate_fees_confirmation_required(self):
        self.candidate['cost_includes_fees']=False
        self.assertIn('CANDIDATE_FEES_UNCONFIRMED',self.run_review()['reasons'])
    def test_inputs_not_modified_and_permission_injection_ignored(self):
        self.candidate['entry_permission']=True
        original=deepcopy((self.config,self.evidence,self.candidate))
        self.assertFalse(self.run_review()['entry_permission'])
        self.assertEqual(original,(self.config,self.evidence,self.candidate))
    def test_utc_observation_is_scoped_to_ist_session(self):
        self.evidence['observed_at']=self.now.astimezone(__import__('datetime').timezone.utc).isoformat()
        self.assertEqual(self.run_review()['status'],'REVIEWED_ONLY')

if __name__=='__main__':unittest.main()
