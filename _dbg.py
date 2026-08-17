import sys, time
sys.path.insert(0, '.')
from unittest import mock
from tests.test_data_validator import md, TestScannerIntegration
t = TestScannerIntegration(); t.setUp()
from strategies.macd_resonance.scanner import Scanner, PortfolioManager
fetched = {"eastmoney": md(limit_up_count=0, source="eastmoney"), "akshare": md(limit_up_count=45, source="akshare")}
t0 = time.time()
with mock.patch("strategies.macd_resonance.scanner._fetch_both", return_value=fetched) as mf, \
     mock.patch("strategies.macd_resonance.scanner.update_source_status") as ms, \
     mock.patch("strategies.macd_resonance.scanner.get_market_score", return_value=(5.0, "ok", True)) as msc, \
     mock.patch("strategies.macd_resonance.scanner.send_feishu_alert", return_value=True) as ma, \
     mock.patch.object(PortfolioManager, "check_exit_signals", return_value=[]):
    sc = Scanner()
    print("scanner constructed", round(time.time()-t0, 1), "s")
    r = sc.run()
    print("run done", round(time.time()-t0, 1), "s, data_source=", r["data_source"], "summary=", r["summary"])
t.tearDown()
