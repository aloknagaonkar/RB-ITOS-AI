from copy import deepcopy
from datetime import datetime,timezone
from decimal import Decimal
import json
import unittest
from unittest.mock import Mock,patch
from urllib.parse import urlparse,parse_qs
from fee_report import (query,paise,assess_response,FixedChargesClient,NoRedirect,
                        collect_report)
from signature_checks import sign


def sample():
    return dict(status="success",data=dict(charges_breakdown=dict(
        total="154.23",brokerage="97.23",
        taxes=dict(gst="20.93",stt="15",stamp_duty="2"),
        charges=dict(transaction=".56",clearing=0,ipft=None,others=0,
                     sebi_turnover=".01",demat_transaction="18.50"))))


class FeeReportTests(unittest.TestCase):
    def get(self,raw=None,side_effect=None):
        response=Mock()
        response.status=200
        response.read.return_value=json.dumps(sample()).encode() if raw is None else raw
        response.__enter__=Mock(return_value=response)
        response.__exit__=Mock(return_value=False)
        opener=Mock()
        opener.open.return_value=response
        if side_effect:opener.open.side_effect=side_effect
        with patch("fee_report.build_opener",return_value=opener):
            result=FixedChargesClient("fixture-token").get("2026-10-29")
        return result,opener

    def test_april_financial_year(self):
        self.assertEqual(query("2026-04-01")["financial_year"],"2627")

    def test_march_financial_year(self):
        self.assertEqual(query("2026-03-31")["financial_year"],"2526")

    def test_date_range_is_one_explicit_fo_day(self):
        q=query("2026-10-29")
        self.assertEqual(q["from_date"],q["to_date"])
        self.assertEqual(q["segment"],"FO")

    def test_invalid_date_or_url_rejected(self):
        for value in ("2026-02-30","29-10-2026","https://other",None):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):query(value)

    def test_paise_has_no_binary_float_drift(self):
        self.assertEqual(paise(154.23),15423)
        self.assertEqual(paise(Decimal("0.01")),1)

    def test_invalid_money_rejected(self):
        for value in (True,None,-1,"NaN","Infinity","-Infinity"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):paise(value)

    def test_fractional_paise_not_rounded_into_evidence(self):
        with self.assertRaisesRegex(ValueError,"FRACTIONAL_PAISE"):
            paise("1.001")

    def test_sample_total_and_null_component(self):
        r=assess_response(sample())
        self.assertEqual(r["reported_aggregate_total_paise"],15423)
        self.assertEqual(r["missing_or_null_component_paths"],["charges.ipft"])
        self.assertTrue(r["component_arithmetic_matches_total"])
        self.assertFalse(r["fees_complete"])

    def test_zero_report_does_not_prove_complete_strategy_fees(self):
        raw=sample();c=raw["data"]["charges_breakdown"]
        c["total"]=c["brokerage"]=0
        for d in (c["taxes"],c["charges"]):
            for key in d:d[key]=0
        r=assess_response(raw)
        self.assertFalse(r["fees_complete"])
        self.assertFalse(r["trade_fee_attribution_verified"])
        self.assertIsNone(r["realized_net_pnl_paise"])

    def test_missing_total_not_zero(self):
        raw=sample();del raw["data"]["charges_breakdown"]["total"]
        with self.assertRaisesRegex(ValueError,"AGGREGATE_TOTAL_UNAVAILABLE"):
            assess_response(raw)

    def test_error_response_is_not_old_success(self):
        with self.assertRaisesRegex(ValueError,"CHARGES_PROVIDER_NOT_SUCCESS"):
            assess_response(dict(status="error",message="private-provider-message"))

    def test_components_exceeding_total_block(self):
        raw=sample();raw["data"]["charges_breakdown"]["total"]="1"
        with self.assertRaisesRegex(ValueError,"COMPONENT_SUM_EXCEEDS"):
            assess_response(raw)

    def test_unexplained_total_remainder_not_complete(self):
        raw=sample();raw["data"]["charges_breakdown"]["total"]="155"
        r=assess_response(raw)
        self.assertFalse(r["component_arithmetic_matches_total"])
        self.assertFalse(r["fees_complete"])

    def test_injected_authority_flags_ignored(self):
        raw=sample();raw.update(fees_complete=True,entry_permission=True)
        r=assess_response(raw)
        self.assertFalse(r["fees_complete"]);self.assertFalse(r["entry_permission"])

    def test_inputs_unchanged(self):
        raw=sample();before=deepcopy(raw)
        assess_response(raw);self.assertEqual(raw,before)

    def test_only_fixed_get_endpoint_used(self):
        _,opener=self.get()
        request=opener.open.call_args.args[0]
        parsed=urlparse(request.full_url)
        self.assertEqual(request.get_method(),"GET")
        self.assertEqual(parsed.netloc,"api.upstox.com")
        self.assertEqual(parsed.path,"/v2/trade/profit-loss/charges")
        self.assertEqual(parse_qs(parsed.query)["segment"],["FO"])

    def test_redirects_rejected(self):
        with self.assertRaisesRegex(ValueError,"REPORT_REDIRECT_FORBIDDEN"):
            NoRedirect().redirect_request(None,None,None,None,None,None)

    def test_response_size_bounded(self):
        with self.assertRaisesRegex(ValueError,"CHARGES_RESPONSE_TOO_LARGE"):
            self.get(raw=b"x"*262145)

    def test_invalid_json_sanitized(self):
        with self.assertRaisesRegex(ValueError,"CHARGES_RESPONSE_INVALID"):
            self.get(raw=b"private non-json provider response")

    def test_duplicate_json_keys_rejected(self):
        with self.assertRaisesRegex(ValueError,"DUPLICATE_REPORT_JSON_KEY"):
            self.get(raw=b'{"status":"success","status":"error"}')

    def test_network_failure_has_no_retry_or_raw_message(self):
        opener=Mock();opener.open.side_effect=RuntimeError("private-token-message")
        with patch("fee_report.build_opener",return_value=opener):
            with self.assertRaisesRegex(ValueError,"CHARGES_GET_FAILED_NO_RETRY"):
                FixedChargesClient("fixture-token").get("2026-10-29")
        self.assertEqual(opener.open.call_count,1)

    def collect(self,matches=None,times=None):
        profile=Mock();profile.get.return_value={"fixture_profile":True}
        charges=Mock();charges.get.return_value=sample()
        pin=dict(scope="FIXTURE:FEES",key="11"*32)
        times=times or [datetime(2026,10,29,5,30,tzinfo=timezone.utc),
                       datetime(2026,10,29,5,30,1,tzinfo=timezone.utc)]
        match=matches or Mock()
        result=collect_report(profile,charges,pin,matches=match,
                              clock=Mock(side_effect=times))
        return result,profile,charges,match,pin

    def test_profile_verified_before_and_after_report(self):
        r,profile,charges,match,pin=self.collect()
        self.assertEqual(profile.get.call_args_list,
                         [unittest.mock.call("profile"),unittest.mock.call("profile")])
        self.assertEqual(match.call_count,2);charges.get.assert_called_once_with("2026-10-29")
        signature=r.pop("signature")
        self.assertEqual(signature,sign(r,pin))
        self.assertFalse(r["assessment"]["risk_gate_input_ready"])

    def test_identity_mismatch_before_report_blocks(self):
        profile=Mock();charges=Mock()
        with self.assertRaisesRegex(ValueError,"WRONG_ACCOUNT"):
            collect_report(profile,charges,dict(scope="FIXTURE",key="11"*32),
                matches=Mock(side_effect=ValueError("WRONG_ACCOUNT")),
                clock=lambda:datetime.now(timezone.utc))
        charges.get.assert_not_called()

    def test_identity_mismatch_after_report_blocks(self):
        with self.assertRaisesRegex(ValueError,"WRONG_ACCOUNT"):
            self.collect(matches=Mock(side_effect=[None,ValueError("WRONG_ACCOUNT")]))

    def test_slow_capture_blocks(self):
        times=[datetime(2026,10,29,5,30,tzinfo=timezone.utc),
               datetime(2026,10,29,5,30,31,tzinfo=timezone.utc)]
        with self.assertRaisesRegex(ValueError,"FEE_CAPTURE_SLOW_OR_SESSION_CHANGED"):
            self.collect(times=times)

    def test_naive_clock_rejected(self):
        with self.assertRaisesRegex(ValueError,"AWARE_TIMESTAMP_REQUIRED"):
            self.collect(times=[datetime(2026,10,29,5,30)])


if __name__=="__main__":
    unittest.main()
