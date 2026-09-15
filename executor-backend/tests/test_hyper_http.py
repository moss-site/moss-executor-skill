import io
import json
import unittest
from unittest.mock import patch, Mock
from urllib.error import HTTPError
from executor_backend.hyper.http import read_json, HyperReadError
from executor_backend.hyper.client import HyperCoreClient
from executor_backend.config import load_config


class ReadTests(unittest.TestCase):
    def test_429_retries_and_401_does_not(self):
        success = Mock()
        success.__enter__ = Mock(return_value=success)
        success.__exit__ = Mock(return_value=False)
        success.read.return_value = b'{"ok":true}'
        with patch('executor_backend.hyper.http.request.urlopen', side_effect=[HTTPError('https://redacted',429,'limit',{'Retry-After':'2'},None), success]) as send, patch('executor_backend.hyper.http.time.sleep') as sleep:
            self.assertEqual(read_json('https://read.example/info', {'type':'meta'}), {'ok':True})
            self.assertEqual(send.call_count,2)
            self.assertGreaterEqual(sleep.call_args.args[0],2)
        with patch('executor_backend.hyper.http.request.urlopen', side_effect=HTTPError('https://redacted',401,'auth',{},None)) as send:
            with self.assertRaises(HyperReadError): read_json('https://read.example/info', {})
            self.assertEqual(send.call_count,1)

    def test_long_retry_after_fails_without_early_retry(self):
        with patch('executor_backend.hyper.http.request.urlopen', side_effect=HTTPError('https://redacted',429,'limit',{'Retry-After':'120'},None)) as send, patch('executor_backend.hyper.http.time.sleep') as sleep:
            with self.assertRaises(HyperReadError) as e: read_json('https://read.example/info', {}, budget=5)
            self.assertGreaterEqual(e.exception.retry_after,120)
            sleep.assert_not_called()

    def test_read_endpoint_override(self):
        with patch.dict('os.environ', {'NETWORK':'mainnet', 'HYPERCORE_API_URL':'https://api.hyperliquid.xyz', 'HYPERCORE_INFO_URL':'https://read.example'}):
            self.assertEqual(load_config().network.hypercore_api_url, 'https://read.example')

    def test_watcher_can_skip_ledger_but_default_nav_cannot(self):
        client = HyperCoreClient('https://read.example', ('main','xyz'))
        clearing={'marginSummary':{'accountValue':'1'}, 'assetPositions':[], 'withdrawable':'1'}
        with patch.object(client, 'clearinghouse_state', return_value=clearing), patch.object(client, 'spot_clearinghouse_state', return_value={'balances':[]}), patch.object(client, 'user_non_funding_ledger_updates', return_value=[{'x':1}]) as ledger:
            state=client.fetch_state('0x1', include_ledger=False)
            ledger.assert_not_called()
            self.assertFalse(state.ledger_included)
            state=client.fetch_state('0x1')
            ledger.assert_called_once()
            self.assertEqual(state.ledger,[{'x':1}])
            self.assertTrue(state.ledger_included)

    def test_wrong_read_path_rejected_before_requests(self):
        for base in ['https://read.example/hypercore', 'https://read.example/info']:
            with self.assertRaises(ValueError): HyperCoreClient(base)

    def test_read_timeout_retries_bounded_and_never_returns_zero(self):
        with patch('executor_backend.hyper.http.request.urlopen',side_effect=TimeoutError), patch('executor_backend.hyper.http.time.sleep'):
            with self.assertRaises(HyperReadError): read_json('https://read.example/info',{})

    def test_daemon_defers_after_retry_after_and_remains_alive(self):
        from types import SimpleNamespace
        from executor_backend import daemon
        sleeps=[]
        def sleep(seconds):
            sleeps.append(seconds)
            if len(sleeps)==3: raise KeyboardInterrupt
        paths=Mock()
        with patch.object(daemon.RuntimePaths,'from_agent',return_value=paths), patch.object(daemon,'write_json'), patch.object(daemon,'append_jsonl'), patch.object(daemon,'run_once',side_effect=[HyperReadError(429,900),{}]) as run, patch.object(daemon.random,'uniform',return_value=0), patch.object(daemon.time,'sleep',side_effect=sleep):
            with self.assertRaises(KeyboardInterrupt):
                daemon.loop(SimpleNamespace(agent=SimpleNamespace(agent_address='0x1'),network=SimpleNamespace(name='mainnet')),300)
            self.assertEqual(sleeps,[0,900,300])
            self.assertEqual(run.call_count,2)
