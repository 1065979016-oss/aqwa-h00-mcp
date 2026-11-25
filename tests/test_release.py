"""Quick regression suite. No license, external data, network or third-party modules."""
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET

from demo import get_h00_replay_example, chart_svg
from aqwa_full_sea_batch import _html

ROOT = Path(__file__).resolve().parents[1]


class CountingParser(HTMLParser):
    bars = 0

    def handle_starttag(self, tag, attrs):
        self.bars += dict(attrs).get('class') == 'bar'
        if tag == 'script':
            raise AssertionError('HTML does not require JavaScript.')


class ReleaseTest(unittest.TestCase):
    def test_offline_figures_and_block(self):
        report = get_h00_replay_example()
        self.assertEqual(report['data_mode'],'synthetic_replay')
        self.assertFalse(report['solver_invoked'])
        self.assertEqual([r['status'] for r in report['cases']],['completed','completed','blocked'])
        self.assertNotIn('result',report['cases'][2])
        self.assertGreater(report['cases'][2]['minimum_suggested_hydrodynamic_endpoints_hz'][1],.28)
        html = _html(report)
        self.assertIn('合成数据 · 未调用 AQWA',html)
        parser = CountingParser()
        parser.feed(html)
        self.assertEqual(parser.bars,4)
        svg = chart_svg(report)
        self.assertIn('NO AQWA SOLVE',svg)
        self.assertIn('0.920',svg)
        ET.fromstring(svg)

    def test_stdio_without_private_assets(self):
        def message(num, method, **params):
            return {'jsonrpc':'2.0','id':num,'method':method,'params':params}
        packet = [
            message(1,'initialize',protocolVersion='2025-11-25',capabilities={},
                    clientInfo={'name':'test','version':'1.0'}),
            {'jsonrpc':'2.0','method':'notifications/initialized'},
            message(2,'tools/list'),
            message(3,'tools/call',name='get_h00_replay_example',arguments={}),
            message(4,'tools/call',name='preview_h00_full_sea_batch',arguments={
                'cases':json.loads((ROOT/'examples/sea_states.json').read_text(encoding='utf-8'))}),
        ]
        env = {k:v for k,v in os.environ.items() if not k.startswith('AQWA_MCP_')}
        run = subprocess.run([sys.executable,'-B',str(ROOT/'mcp_server.py')],input='\n'.join(map(json.dumps,packet))+'\n',
                             text=True,capture_output=True,env=env,timeout=15,check=True)
        reply = {p['id']:p['result'] for p in map(json.loads,run.stdout.splitlines())}
        self.assertEqual(reply[1]['serverInfo']['version'],'0.1.0')
        self.assertEqual(len(reply[2]['tools']),5)
        self.assertFalse(reply[3]['structuredContent']['solver_invoked'])
        self.assertTrue(reply[4]['isError'])
        self.assertIn('AQWA_MCP_INPUTS',reply[4]['content'][0]['text'])


if __name__ == '__main__':
    unittest.main()
