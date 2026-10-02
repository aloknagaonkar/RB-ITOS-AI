from datetime import date, datetime
import json
from pathlib import Path
import pytest

from market_lab.domain import HistoricalCandle, IST
from market_lab.live_option_minute_source_v1 import CompletedOptionMinute
from market_lab.hilega_market_evidence_v1 import (
    EvidenceJournalV1, RecordingHilegaSourcesV1, PlaybackHilegaSourcesV1,
    verify_journal,
)


class FakeSource:
    def __init__(self):
        self.calls = 0

    def nifty_intraday_1m(self, *, now=None):
        self.calls += 1
        return [HistoricalCandle(provider="upstox", instrument_key="NSE_INDEX|Nifty 50",
                                  session_date=date(2026, 9, 23), interval_seconds=60,
                                  timestamp=datetime(2026, 9, 23, 9, 15, tzinfo=IST),
                                  open=23400, high=23401, low=23399, close=23400,
                                  volume=123)]

    def option_contracts(self, underlying, expiry):
        self.calls += 1
        return [{"instrument_key": "NSE_FO|1", "expiry_date": expiry.isoformat(),
                 "strike_price": 23400, "instrument_type": "CE"}]

    def option_intraday_1m(self, instrument_key):
        self.calls += 1
        return [CompletedOptionMinute(instrument_key, datetime(2026,9,23,9,15,tzinfo=IST),
                                      30, 31, 29, 30.5, 100)]


def test_roundtrip_without_broker(tmp_path):
    path=tmp_path/"journal.jsonl"
    upstream=FakeSource()
    journal=EvidenceJournalV1(path)
    source=RecordingHilegaSourcesV1(upstream, journal)
    now=datetime(2026,9,23,9,15,30,tzinfo=IST)
    source.tick(now)
    assert source.nifty_intraday_1m(now=now)[0].close == 23400
    source.option_contracts("NSE_INDEX|Nifty 50", date(2026,9,29))
    source.option_intraday_1m("NSE_FO|1")
    source.close()
    assert upstream.calls == 3
    assert len(verify_journal(path)) == 4
    playback=PlaybackHilegaSourcesV1(path)
    assert playback.next_tick()==now
    assert playback.nifty_intraday_1m(now=now)[0].close == 23400
    assert playback.option_contracts("NSE_INDEX|Nifty 50", date(2026,9,29))[0]["instrument_key"] == "NSE_FO|1"
    assert playback.option_intraday_1m("NSE_FO|1")[0].close == 30.5
    playback.assert_consumed()


def test_journal_tamper_is_detected(tmp_path):
    path=tmp_path/"journal.jsonl"
    journal=EvidenceJournalV1(path)
    journal.append("tick", {"now":"2026-09-23T09:15:30+05:30"})
    journal.close()
    path.write_bytes(path.read_bytes().replace(b"09:15", b"09:16"))
    with pytest.raises(ValueError, match="DIGEST"):
        verify_journal(path)


def test_playback_fails_closed_on_diverged_call(tmp_path):
    path=tmp_path/"journal.jsonl"
    journal=EvidenceJournalV1(path)
    source=RecordingHilegaSourcesV1(FakeSource(), journal)
    now=datetime(2026,9,23,9,15,30,tzinfo=IST)
    source.tick(now)
    source.nifty_intraday_1m(now=now)
    source.close()
    playback=PlaybackHilegaSourcesV1(path)
    playback.next_tick()
    with pytest.raises(ValueError, match="DIVERGENCE"):
        playback.option_intraday_1m("NSE_FO|1")


def test_append_restart_preserves_chain(tmp_path):
    path=tmp_path/"journal.jsonl"
    j=EvidenceJournalV1(path)
    j.append("tick", {"now":"one"})
    j.close()
    k=EvidenceJournalV1(path)
    k.append("tick", {"now":"two"})
    k.close()
    rows=verify_journal(path)
    assert [r['sequence'] for r in rows]==[1,2]
    assert rows[1]['previous_hash']==rows[0]['record_hash']


def test_empty_source_response_is_preserved(tmp_path):
    class Empty(FakeSource):
        def option_intraday_1m(self, instrument_key):
            return []
    path=tmp_path/"journal.jsonl"
    j=EvidenceJournalV1(path)
    s=RecordingHilegaSourcesV1(Empty(),j)
    assert s.option_intraday_1m('NSE_FO|1') == []
    s.close()
    assert PlaybackHilegaSourcesV1(path).option_intraday_1m('NSE_FO|1') == []


def test_repeated_poll_response_is_deduplicated_but_replayable(tmp_path):
    path=tmp_path/"journal.jsonl"
    now=datetime(2026,9,23,9,15,30,tzinfo=IST)
    j=EvidenceJournalV1(path)
    s=RecordingHilegaSourcesV1(FakeSource(),j)
    s.tick(now)
    s.nifty_intraday_1m(now=now)
    s.nifty_intraday_1m(now=now)
    s.close()
    disk=[json.loads(line) for line in path.read_text().splitlines()]
    assert disk[2].get('response_ref')
    assert 'response' not in disk[2]
    replay=PlaybackHilegaSourcesV1(path)
    replay.next_tick()
    assert replay.nifty_intraday_1m(now=now)==replay.nifty_intraday_1m(now=now)
    replay.assert_consumed()
