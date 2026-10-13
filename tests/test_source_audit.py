"""Offline regressions for recovered source behavior; no live scraping."""
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'ACEE'))


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class SourceAuditTests(unittest.TestCase):
    def test_capt_reads_all_saved_pages_once(self):
        module = load('audit_capt', 'Kuwait/CAPT/capt_awarded_scraper.py')
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            first = folder / 'capt_winning_bids_browser_response.html'
            first.write_text('page one')
            (folder / 'capt_winning_bids_browser_response_page2.html').write_text('page two')
            (folder / 'unrelated.html').write_text('ignore')
            with patch.object(module, 'SAVED_BROWSER_CAPTURE_PATH', first), patch.object(
                module, 'parse_award_rows', side_effect=lambda html, url: [html]
            ) as parse:
                self.assertEqual(module.load_saved_browser_capture_rows(), ['page one', 'page two'])
                self.assertEqual(parse.call_count, 2)

    def test_acee_registry_modules_are_loadable_without_fixtures(self):
        from harness.sources.loader import load_source_module
        from harness.sources.registry import feasible_sources
        sources = feasible_sources()
        self.assertEqual(len(sources), 12)
        for source in sources:
            module = load_source_module(source.key)
            self.assertTrue(callable(module.smoke_probe), source.key)

    def test_romania_cpv_query_preserves_filters(self):
        module = load('audit_romania', 'romania-seap/ro_seap_scraper.py')
        query = module._build_ted_query(published_from='2024-01-01', published_to='2026-10-13',
            query_text='medical', buyer_name='hospital', cpv_codes=['33100000', '33600000'])
        self.assertIn('classification-cpv=33100000 OR classification-cpv=33600000', query)
        self.assertIn('publication-date<=20261013', query)
        self.assertIn('place-of-performance-country-proc=ROU', query)

    def test_poland_notebook_run_cell_is_real_python(self):
        notebook = json.loads((ROOT / 'poland-ezamowienia/ezamowienia_scraper_notebook.ipynb').read_text())
        cell = next(c for c in notebook['cells'] if c['metadata'].get('id') == 'run')
        scope = {key: '' for key in ['DATE_FROM','DATE_TO','QUERY','OUTPUT_TARGET','PROJECT_NAME',
                 'WEBSITE_ID','SOURCE_LABEL','REGION','NOTICE_TYPE','SORTING_COLUMN','SORTING_DIRECTION']}
        scope.update(PAGE_NUMBER=1, PAGE_SIZE=50, BELOW_EU=True)
        with patch('subprocess.run') as run:
            exec(compile(''.join(cell['source']), '<notebook run>', 'exec'), scope)
            self.assertIn('--below-eu', run.call_args.args[0])
            self.assertTrue(run.call_args.kwargs['check'])

    def test_turkey_preserves_turkish_money_scale(self):
        module = load('audit_turkey', 'memory_sources/TURMECA/agent_work/turkey_repair_v2/adapter/turkey_ekap_adapter_v2.py')
        self.assertEqual(module.money('1.995.962,60 TRY'), (1995962.60, 'TRY'))
        self.assertEqual(module.money('6.150 TL'), (6150.0, 'TRY'))

    def test_nupco_does_not_treat_booklet_price_or_generic_qty_as_award(self):
        module = load('audit_nupco', 'memory_sources/TURMECA/agent_work/ksa_repair_v2/nupco_adapter_v2.py')
        result = module.Adapter._explicit_fields('Tender Booklet Price: SAR 9200; QTY 1083')
        self.assertEqual([result[k] for k in ['amount','currency','quantity','period']], ['', '', '', ''])
        result = module.Adapter._explicit_fields('AWARD VALUE: SAR 1500; QUANTITY AWARDED: 10')
        self.assertEqual(result['currency'], 'SAR')
        self.assertEqual(result['quantity'], '10')

    def test_colombia_rejects_reversed_dates_before_network(self):
        module = load('audit_colombia', 'colombia-secop/extract.py')
        self.assertEqual(module.END_DATE, date.today().isoformat())
        with patch.object(module, 'fetch_window') as fetch, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                module.main(['--date-from','2026-10-13','--date-to','2024-01-01'])
            self.assertEqual(raised.exception.code, 2)
            fetch.assert_not_called()

    def test_nupco_missing_snapshot_is_not_successful_empty_extraction(self):
        module = load('audit_nupco_missing', 'memory_sources/TURMECA/agent_work/ksa_repair_v2/nupco_adapter_v2.py')
        with tempfile.TemporaryDirectory() as tmp:
            adapter = module.Adapter(output_root=tmp)
            with self.assertRaisesRegex(FileNotFoundError, 'not a zero-award result'):
                adapter.extract()

    def test_malaysia_rejects_invalid_dates_before_browser(self):
        module = load('audit_eperolehan', 'malaysia-eperolehan/eperolehan_scraper.py')
        self.assertEqual(module.SearchConfig().date_to, date.today().strftime('%d/%m/%Y'))
        with patch.object(sys, 'argv', ['eperolehan_scraper.py','--date-from','not-a-date']), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                module.main()
            self.assertEqual(raised.exception.code, 2)

    def test_catalog_keeps_missing_sources_distinct(self):
        catalog = json.loads((ROOT / 'docs/country_website_catalog.json').read_text())
        for country, portal in [('Panama','PanamaCompra'), ('Spain','National procurement portal'), ('Egypt','eTenders')]:
            entry = next(r for r in catalog if r['country']==country and r['portal']==portal)
            self.assertEqual(entry['scripts'], [])
            self.assertFalse(entry['live_data_refreshed'])


if __name__ == '__main__':
    unittest.main()
