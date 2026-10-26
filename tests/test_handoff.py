import copy
import json
from pathlib import Path
import signal
import tempfile
import unittest
from unittest.mock import patch

from seethis_runs import mcp_server
from seethis_runs.log_reader import read_run
from seethis_runs.store import Store

REF = 'a' * 32


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.logs = self.root / 'sessions'; self.logs.mkdir()
        self.store = Store(self.root / 'private/runs.json', self.logs)
        self.a = self.start('a')
        self.b = self.start('b')

    def tearDown(self):
        signal.setitimer(signal.ITIMER_REAL, 0)
        self.temp.cleanup()

    def start(self, session):
        path = self.logs / (session + '.jsonl')
        events = [{'type': 'session_meta', 'payload': {'id': session}},
                  {'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': 'turn-' + session}},
                  {'type': 'response_item', 'timestamp': '2026-10-25T00:00:00Z', 'payload': {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': 'SYNTHETIC_BODY_' + session}]}}]
        lines = [(json.dumps(e) + '\n').encode() for e in events]
        path.write_bytes(b''.join(lines))
        locator = {'path': str(path), 'byte': len(lines[0]), 'turn_id': 'turn-' + session, 'ordinal': None}
        with patch('seethis_runs.store.log_locator', return_value=locator):
            self.store.start([REF], session, 'turn-' + session, str(path))
        return self.store.progress(REF)[0]['run_id']

    def confirm(self, session='b', source=None):
        return self.store.confirm_takeover(REF, session, source or self.a)

    def commit(self, confirmation, session='b'):
        return self.store.commit_handoff(REF, session, confirmation['confirmation_id'])

    def record(self, run_id):
        return next(r for r in self.store.progress(REF) if r['run_id'] == run_id)

    def test_confirm_does_not_transfer_and_retry_is_idempotent(self):
        old = self.record(self.a)
        confirmation = self.confirm()
        self.assertEqual(confirmation, self.confirm())
        self.assertEqual(self.record(self.a), old)
        self.assertIsNone(self.record(self.b)['current_segment'])
        self.assertEqual(confirmation['state'], 'confirmed')
        self.assertTrue(self.record(self.b)['pending_handoffs'])
        self.assertNotIn('SYNTHETIC_BODY', self.store.path.read_text())

    def test_commit_persists_positions_chain_and_retry(self):
        old = self.record(self.a); confirmation = self.confirm()
        result = self.commit(confirmation)
        self.assertEqual(result, self.commit(confirmation))
        a, b = self.record(self.a), self.record(self.b)
        self.assertEqual(a['start'], old['start'])
        self.assertEqual(a['status'], 'transferred'); self.assertFalse(a['current_segment'])
        self.assertEqual(a['handoff_end']['locator'], confirmation['source_end'])
        self.assertTrue(b['current_segment']); self.assertEqual(b['handoff_start'], confirmation['target_start'])
        self.assertEqual(b['handoff_from']['run_id'], self.a)
        self.assertEqual(len(self.store.progress(REF)), 2)
        self.assertEqual(Store(self.store.path, self.logs).progress(REF), self.store.progress(REF))
        self.assertFalse(read_run(REF, self.a, self.store, self.logs)['interval']['live_snapshot'])
        self.assertTrue(read_run(REF, self.b, self.store, self.logs)['interval']['live_snapshot'])

    def test_frozen_old_cutoff_excludes_later_records(self):
        confirmation = self.confirm(); cutoff = confirmation['source_end']['byte']
        with (self.logs / 'a.jsonl').open('ab') as out:
            out.write(b'{"type":"later"}\n')
        self.commit(confirmation)
        value = read_run(REF, self.a, self.store, self.logs)
        self.assertEqual(value['interval']['end_byte'], cutoff)
        self.assertEqual(len(value['messages']), 1)

    def test_late_old_callbacks_do_not_change_successor_or_history(self):
        self.commit(self.confirm()); before = self.store.progress(REF)
        with self.assertRaisesRegex(ValueError, 'segment_transferred'):
            self.store.end(REF, 'a', 'done', 'Late ending')
        self.store.infer('a', 'turn-a', 'Stop')
        self.store.infer('a', None, 'SessionEnd')
        self.assertEqual(before, self.store.progress(REF))

    def test_missing_or_wrong_confirmation_cannot_commit(self):
        confirmation = self.confirm(); before = self.store.path.read_bytes()
        for ref, session, token in [(REF, 'a', confirmation['confirmation_id']), ('c' * 32, 'b', confirmation['confirmation_id']), (REF, 'b', 'missing')]:
            with self.assertRaisesRegex(ValueError, 'confirmation_not_owned'):
                self.store.commit_handoff(ref, session, token)
        self.assertEqual(before, self.store.path.read_bytes())

    def test_changed_source_or_target_requires_fresh_confirmation(self):
        confirmation = self.confirm()
        self.store.end(REF, 'a', 'done', 'Finished before handoff')
        self.assertFalse(self.record(self.b)['pending_handoffs'])
        before = self.store.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'source_already_ended'):
            self.commit(confirmation)
        self.assertEqual(before, self.store.path.read_bytes())

    def test_target_stop_or_new_turn_rejects_stale_commit(self):
        confirmation = self.confirm(); self.store.infer('b', 'turn-b', 'Stop')
        before = self.store.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'target_not_open'):
            self.commit(confirmation)
        self.assertEqual(before, self.store.path.read_bytes())

    def test_competing_incoming_agents_cannot_both_take_source(self):
        c = self.start('c'); b_confirmation = self.confirm(); c_confirmation = self.confirm('c')
        self.commit(b_confirmation)
        self.assertFalse(self.record(c)['pending_handoffs'])
        before = self.store.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'source_already_ended'):
            self.commit(c_confirmation, 'c')
        self.assertEqual(before, self.store.path.read_bytes())
        self.assertIsNone(self.record(c)['current_segment'])

    def test_chained_transfer_and_old_retry_never_restore_old_pointer(self):
        first = self.confirm(); self.commit(first)
        c = self.start('c'); second = self.confirm('c', self.b); self.commit(second, 'c')
        self.commit(first)
        self.assertTrue(self.record(c)['current_segment']); self.assertFalse(self.record(self.b)['current_segment'])
        self.assertEqual(self.record(c)['chain_id'], self.a)
        self.assertEqual(self.record(self.b)['handoff_from']['run_id'], self.a)

    def test_paused_source_preserves_inference_and_its_original_cutoff(self):
        path = self.logs / 'a.jsonl'; cutoff = path.stat().st_size
        loc = {'path': str(path), 'byte': cutoff, 'turn_id': 'turn-a'}
        with patch('seethis_runs.store.log_locator', return_value=loc):
            self.store.infer('a', 'turn-a', 'Interrupt', str(path))
        inference = copy.deepcopy(self.record(self.a)['inferred_end'])
        with path.open('ab') as out: out.write(b'{"type":"later"}\n')
        self.commit(self.confirm())
        self.assertEqual(self.record(self.a)['inferred_end'], inference)
        self.assertEqual(self.record(self.a)['handoff_end']['locator']['byte'], cutoff)

    def test_missing_start_end_and_wrong_session_fail_without_write(self):
        for change in ('missing', 'wrong-session', 'missing-end'):
            original = self.store.path.read_bytes(); data = json.loads(original)
            source = data['references'][REF][0]
            if change == 'missing': source['start']['locator']['byte'] = None
            elif change == 'wrong-session': source['session_id'] = 'not-a'
            else: source['inferred_end'] = {'status': 'interrupted', 'source': 'hook', 'locator': {}}
            self.store.path.write_text(json.dumps(data)); before = self.store.path.read_bytes()
            with self.assertRaises(ValueError): self.confirm()
            self.assertEqual(before, self.store.path.read_bytes()); self.store.path.write_bytes(original)

    def test_truncated_or_replaced_file_does_not_transfer(self):
        confirmation = self.confirm(); before = self.store.path.read_bytes()
        path = self.logs / 'a.jsonl'; raw = path.read_bytes(); path.write_bytes(raw[:-20])
        with self.assertRaisesRegex(ValueError, 'interval_truncated'): self.commit(confirmation)
        self.assertEqual(before, self.store.path.read_bytes()); path.write_bytes(raw)
        replacement = self.logs / 'replacement.jsonl'; replacement.write_bytes(raw); replacement.replace(path)
        with self.assertRaisesRegex(ValueError, 'log_file_replaced'): self.commit(confirmation)
        self.assertEqual(before, self.store.path.read_bytes())

    def test_partial_trailing_record_is_not_saved_as_cutoff(self):
        path = self.logs / 'a.jsonl'; cutoff = path.stat().st_size
        with path.open('ab') as out: out.write(b'{"partial":')
        confirmation = self.confirm(); self.commit(confirmation)
        self.assertEqual(self.record(self.a)['handoff_end']['locator']['byte'], cutoff)

    def test_other_turn_cannot_be_included_in_handoff_interval(self):
        with (self.logs / 'a.jsonl').open('ab') as out:
            out.write(b'{"type":"event_msg","payload":{"type":"task_started","turn_id":"next"}}\n')
        with self.assertRaisesRegex(ValueError, 'turn_has_advanced'): self.confirm()

    def test_atomic_write_failure_keeps_original_active_segment(self):
        confirmation = self.confirm(); before = self.store.path.read_bytes()
        with patch('seethis_runs.store.os.replace', side_effect=OSError('synthetic failure')):
            with self.assertRaises(OSError): self.commit(confirmation)
        self.assertEqual(before, self.store.path.read_bytes())
        self.assertEqual(self.record(self.a)['status'], 'in-progress')

    def test_mcp_requires_host_identity_then_confirms_and_commits(self):
        def call(name, args, session=None):
            params = {'name': name, 'arguments': args}
            if session: params['_meta'] = {'threadId': session}
            with patch.object(mcp_server, 'Store', return_value=self.store):
                return json.loads(mcp_server.dispatch({'method': 'tools/call', 'params': params})['content'][0]['text'])
        args = {'reference': REF, 'from_run_id': self.a}
        self.assertEqual(call('confirm_takeover', args)['reason'], 'host_thread_id_missing')
        confirmed = call('confirm_takeover', args, 'b')
        self.assertTrue(confirmed['recorded']); self.assertEqual(self.record(self.a)['status'], 'in-progress')
        committed = call('commit_handoff', {'reference': REF, 'confirmation_id': confirmed['handoff']['confirmation_id']}, 'b')
        self.assertTrue(committed['recorded']); self.assertEqual(committed['handoff']['state'], 'committed')

    def test_old_store_migrates_only_on_write_without_losing_runs(self):
        data = json.loads(self.store.path.read_text()); data['schema_version'] = 1
        self.store.path.write_text(json.dumps(data)); old = copy.deepcopy(data['references'])
        self.store.progress(REF); self.assertEqual(json.loads(self.store.path.read_text())['schema_version'], 1)
        self.confirm(); updated = json.loads(self.store.path.read_text())
        self.assertEqual(updated['schema_version'], 2); self.assertEqual(updated['references'], old)


if __name__ == '__main__': unittest.main()
