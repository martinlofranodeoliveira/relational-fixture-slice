from fixture_slice.demo import run
from support import DatabaseCase


class DemoTests(DatabaseCase):
    def test_asserting_report_has_all_acceptance_cases(self):
        report = run(self.lab, self.root, verify=True)
        self.assertEqual(report['status'], 'ok')
        self.assertEqual([c['rows'] for c in report['cases']], [3, 4, 2, 1, 2, 3])
        self.assertEqual([c['code'] for c in report['rejections']], ['ROW_CAP', 'UNSUPPORTED_SCHEMA', 'FOREIGN_KEY'])
        self.assertEqual(report['rejections'][-1]['retry_rows'], 3)
