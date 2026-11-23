import copy
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
import sys
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.orchestration import team_control as t
from scripts.orchestration.budget_scheduler import evaluate_budget
from scripts.orchestration import antigravity_quota

FIX = Path(__file__).resolve().parent / 'fixtures'

class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.config = t.read_json(FIX / 'ai-team.json')
        self.data = {'checked_at':t.now().isoformat(), 'codex_models':[
            {'model':c['model'],'efforts':['medium']} for c in self.config['candidates'] if c['agent']=='codex'],
            'providers':{name:{'status':'ok','updated_at_ms':t.now().timestamp()*1000,
                'windows':[{'used_percent':value}]} for name,value in [('codex',43),('claude',18),('cursor',0),('antigravity',0)]}}
        # Codex gate tests must not pass through a fallback provider.
        self.codex_only=dict(self.config, candidates=[c for c in self.config['candidates'] if c['agent']=='codex'])

    def test_normal_development_prefers_grok_without_fast_variant(self):
        route = t.choose(self.data, self.config)
        self.assertEqual((route['agent'], route['model']), ('cursor', 'grok-4.7-high'))
        grok = next(c for c in self.config['candidates'] if c['model'] == 'grok-4.7-high')
        self.assertIn('STANDARD', grok['classes'])
        self.assertNotIn('FAST', grok['classes'])
        self.assertNotIn('-fast', route['model'])

    def test_lightweight_iteration_prefers_luna(self):
        self.assertEqual(t.choose(self.data, self.config, 'FAST', 'coder')['model'], 'gpt-6-luna')
        self.assertEqual(t.choose(self.data, self.config, 'FAST', 'research')['model'], 'gpt-6-luna')

    def test_quota_closed_and_no_auto_upgrade(self):
        self.data['providers']['codex']['windows'][0]['used_percent']=98
        self.assertTrue(t.choose(self.data,self.codex_only)['blocked'])

    def test_expiring_underused_short_window_prioritized(self):
        config=copy.deepcopy(self.config)
        config.pop('routing_preferences', None)
        c=copy.deepcopy(config['candidates'][0]); c.update(agent='cursor',model='composer-2.5',origin='cursor')
        config['candidates'].insert(0,c)
        self.data['providers']['cursor']['windows']=[{'window':'monthly','used_percent':55,
            'window_minutes':43200,'resets_at':(t.now().timestamp()+30240*60)*1000}]
        self.data['providers']['codex']['windows']=[{'window':'session','used_percent':30,
            'window_minutes':300,'resets_at':(t.now().timestamp()+30*60)*1000}]
        self.assertEqual(t.choose(self.data,config)['agent'],'codex')

    def test_cursor_routes_on_buckets_not_plan_total(self):
        reset=(t.now().timestamp()+27*24*3600)*1000
        rate={'status':'ok','updatedAt':t.now().timestamp()*1000,
            'monthly':{'usedPercent':100,'windowMinutes':43200,'resetsAt':reset},
            'buckets':[{'name':'Cursor Models','usedPercent':6,'windowMinutes':43200,'resetsAt':reset},
                       {'name':'Other Models','usedPercent':24,'windowMinutes':43200,'resetsAt':reset}]}
        with patch.object(t,'load_config',return_value=self.config), patch.object(t,'cli',return_value={'ok':True,'result':{'rateLimits':{'cursor':rate}}}), \
             patch.object(t.antigravity_quota,'probe',return_value={'status':'unknown','windows':[]}), patch.object(t, 'save_json'):
            cursor=t.snapshot()['providers']['cursor']
        self.assertEqual(cursor['windows'][0]['used_percent'],24)
        self.assertEqual(cursor['models']['composer-2.5'][0]['used_percent'],6)
        self.assertEqual(cursor['models']['grok-4.7-high'][0]['used_percent'],6)
        self.assertEqual(cursor['models']['claude-opus-5-5-high'][0]['used_percent'],24)
        self.assertEqual(t.model_provider({'providers':{'cursor':cursor}},
            {'agent':'cursor','model':'claude-fable-5-1-high'})['windows'][0]['used_percent'],24)

    def test_antigravity_routes_on_buckets_not_worst_weekly(self):
        now_ms = t.now().timestamp() * 1000
        reset_week = (t.now().timestamp() + 5 * 24 * 3600) * 1000
        reset_5h = (t.now().timestamp() + 3 * 3600) * 1000
        rate = {
            'status': 'ok', 'updatedAt': now_ms,
            'session': {'usedPercent': 12, 'windowMinutes': 300, 'resetsAt': reset_5h},
            'weekly': {'usedPercent': 100, 'windowMinutes': 10080, 'resetsAt': reset_week},
            'buckets': [
                {'name': 'Gemini Models · Weekly', 'group': 'Gemini Models',
                 'windowName': 'Weekly Limit Remaining', 'usedPercent': 12,
                 'windowMinutes': 10080, 'resetsAt': reset_week},
                {'name': 'Gemini Models · Five Hour', 'group': 'Gemini Models',
                 'windowName': 'Five Hour Limit Remaining', 'usedPercent': 12,
                 'windowMinutes': 300, 'resetsAt': reset_5h},
                {'name': 'Claude and GPT models', 'group': 'Claude and GPT models',
                 'windowName': 'Weekly Limit Remaining', 'usedPercent': 100,
                 'windowMinutes': 10080, 'resetsAt': reset_week},
                {'name': 'Gemini 4 Argon', 'group': 'Gemini 4 Argon',
                 'windowName': 'Gemini 4 Argon Weekly Limit', 'usedPercent': 21,
                 'windowMinutes': 10080, 'resetsAt': reset_week},
            ],
        }
        with patch.object(t, 'load_config', return_value=self.config), \
             patch.object(t, 'cli', return_value={'ok': True, 'result': {'rateLimits': {'antigravity': rate}}}), \
             patch.object(t, 'save_json'):
            data = t.snapshot()
        ag = data['providers']['antigravity']
        self.assertEqual([w['used_percent'] for w in ag['models']['gemini-4-argon-medium']], [21])
        self.assertEqual([w['used_percent'] for w in ag['models']['claude-opus-5-5-medium']], [100])
        neon = t.model_provider(data, {'agent': 'antigravity', 'model': 'gemini-4-neon-medium'})
        self.assertEqual(sorted((w['window'], w['used_percent']) for w in neon['windows']),
                         [('session', 12), ('weekly', 12)])
        ag_only = dict(self.config, candidates=[c for c in self.config['candidates'] if c['agent'] == 'antigravity'])
        route = t.choose(data, ag_only, 'STRONG', 'reviewer')
        self.assertFalse(route['blocked'])
        self.assertEqual(route['model'], 'gemini-4-argon-medium')
        rejected = {r['model']: r['reason'] for r in route['rejected']}
        self.assertIn('hard stop', rejected['claude-sonnet-5-5-high'])

    def test_claude_fable_weekly_does_not_block_non_fable_models(self):
        now_ms = t.now().timestamp() * 1000
        reset_week = (t.now().timestamp() + 2 * 24 * 3600) * 1000
        rate = {
            'status': 'ok', 'updatedAt': now_ms,
            'weekly': {'usedPercent': 73, 'windowMinutes': 10080, 'resetsAt': reset_week},
            'fableWeekly': {'usedPercent': 100, 'windowMinutes': 10080, 'resetsAt': reset_week},
        }
        with patch.object(t, 'load_config', return_value=self.config), \
             patch.object(t, 'cli', return_value={'ok': True, 'result': {'rateLimits': {'claude': rate}}}), \
             patch.object(t.antigravity_quota, 'probe', return_value={'status': 'unknown', 'windows': []}), \
             patch.object(t, 'save_json'):
            data = t.snapshot()
        claude_only = dict(self.config, candidates=[
            {'agent': 'claude', 'model': 'sonnet', 'effort': None, 'origin': 'anthropic',
             'classes': ['STRONG'], 'roles': ['reviewer'], 'enabled': True},
            {'agent': 'claude', 'model': 'claude-fable-5-1', 'effort': None, 'origin': 'anthropic',
             'classes': ['STRONG'], 'roles': ['reviewer'], 'enabled': True},
        ])
        route = t.choose(data, claude_only, 'STRONG', 'reviewer')
        self.assertFalse(route['blocked'])
        self.assertEqual(route['model'], 'sonnet')
        rejected = {r['model']: r['reason'] for r in route['rejected']}
        self.assertIn('fableWeekly', rejected['claude-fable-5-1'])

    def test_snapshot_prefers_active_account_latest_usage(self):
        now_ms = t.now().timestamp() * 1000
        reset_week = (t.now().timestamp() + 5 * 24 * 3600) * 1000
        old_rate = {
            'status': 'ok', 'updatedAt': now_ms - 60_000,
            'weekly': {'usedPercent': 100, 'windowMinutes': 10080, 'resetsAt': reset_week},
            'usageMetadata': {'account': {'id': 'acc-old'}},
        }
        new_usage = {
            'status': 'ok', 'updatedAt': now_ms,
            'weekly': {'usedPercent': 5, 'windowMinutes': 10080, 'resetsAt': reset_week},
            'buckets': [
                {'name': 'Gemini Models · Weekly', 'group': 'Gemini Models',
                 'usedPercent': 5, 'windowMinutes': 10080, 'resetsAt': reset_week},
            ],
        }
        accounts_reply = {'ok': True, 'result': {
            'rateLimits': {'antigravity': old_rate},
            'antigravity': {
                'activeAccountId': 'acc-new',
                'accounts': [{'id': 'acc-new', 'usage': new_usage}],
            },
        }}
        with patch.object(t, 'load_config', return_value=self.config), \
             patch.object(t, 'cli', return_value=accounts_reply), \
             patch.object(t, 'save_json'):
            data = t.snapshot()
        neon = t.model_provider(data, {'agent': 'antigravity', 'model': 'gemini-4-neon-medium'})
        self.assertEqual(neon['windows'][0]['used_percent'], 5)

    def test_active_account_mismatch_without_usage_blocks_instead_of_stale(self):
        now_ms = t.now().timestamp() * 1000
        reset_week = (t.now().timestamp() + 5 * 24 * 3600) * 1000
        old_rate = {
            'status': 'ok', 'updatedAt': now_ms,
            'weekly': {'usedPercent': 10, 'windowMinutes': 10080, 'resetsAt': reset_week},
            'usageMetadata': {'account': {'id': 'acc-old'}},
        }
        accounts_reply = {'ok': True, 'result': {
            'rateLimits': {'antigravity': old_rate},
            'antigravity': {
                'activeAccountId': 'acc-new',
                'accounts': [{'id': 'acc-new'}],
            },
        }}
        with patch.object(t, 'load_config', return_value=self.config), \
             patch.object(t, 'cli', return_value=accounts_reply), \
             patch.object(t.antigravity_quota, 'probe', return_value={
                 'status': 'ok', 'updated_at_ms': now_ms, 'windows': [],
                 'models': {'gemini-4-argon-medium': [{'window': 'session', 'used_percent': 11,
                                                       'resets_at': reset_week, 'window_minutes': 300}]}
             }) as probe_mock, \
             patch.object(t, 'save_json'):
            data = t.snapshot()
        probe_mock.assert_not_called()
        ag_only = dict(self.config, candidates=[c for c in self.config['candidates'] if c['agent'] == 'antigravity'])
        self.assertTrue(t.choose(data, ag_only, 'STRONG', 'coder')['blocked'])

    def test_seconds_updated_at_normalized_to_ms_and_all_invalid_buckets_block(self):
        now_sec = t.now().timestamp()
        reset_week = (now_sec + 5 * 24 * 3600) * 1000
        claude_rate = {
            'status': 'ok', 'updatedAt': (now_sec - 120) * 1000,
            'weekly': {'usedPercent': 80, 'windowMinutes': 10080, 'resetsAt': reset_week},
        }
        claude_newer = {
            'status': 'ok', 'updatedAt': now_sec,
            'weekly': {'usedPercent': 12, 'windowMinutes': 10080, 'resetsAt': reset_week},
        }
        ag_broken = {
            'status': 'ok', 'updatedAt': now_sec * 1000,
            'weekly': {'usedPercent': 5, 'windowMinutes': 10080, 'resetsAt': reset_week},
            'buckets': [{'name': 123, 'usedPercent': 5}],
        }
        accounts_reply = {'ok': True, 'result': {
            'rateLimits': {'claude': claude_rate, 'antigravity': ag_broken},
            'claude': {'activeAccountId': 'c1', 'accounts': [{'id': 'c1', 'usage': claude_newer}]},
        }}
        with patch.object(t, 'load_config', return_value=self.config), \
             patch.object(t, 'cli', return_value=accounts_reply), \
             patch.object(t, 'save_json'):
            data = t.snapshot()
        claude_only = dict(self.config, candidates=[
            {'agent': 'claude', 'model': 'sonnet', 'effort': None, 'origin': 'anthropic',
             'classes': ['STRONG'], 'roles': ['reviewer'], 'enabled': True},
        ])
        c_route = t.choose(data, claude_only, 'STRONG', 'reviewer')
        self.assertFalse(c_route['blocked'])
        self.assertEqual(c_route['used_percent'], 12)
        ag_only = dict(self.config, candidates=[c for c in self.config['candidates'] if c['agent'] == 'antigravity'])
        self.assertTrue(t.choose(data, ag_only, 'STRONG', 'coder')['blocked'])

    def test_mismatch_error_usage_and_non_list_buckets_stay_blocked(self):
        now_ms = t.now().timestamp() * 1000
        reset_week = (t.now().timestamp() + 5 * 24 * 3600) * 1000
        probe_ok = {'status': 'ok', 'updated_at_ms': now_ms, 'windows': [],
                    'models': {'gemini-4-argon-medium': [{'window': 'session', 'used_percent': 11,
                                                          'resets_at': reset_week, 'window_minutes': 300}]}}
        ag_only = dict(self.config, candidates=[c for c in self.config['candidates'] if c['agent'] == 'antigravity'])
        # 1) Mismatch with error/pending usage must not fall through to local probe
        mismatch_reply = {'ok': True, 'result': {
            'rateLimits': {'antigravity': {'status': 'ok', 'updatedAt': now_ms,
                                           'weekly': {'usedPercent': 10, 'windowMinutes': 10080, 'resetsAt': reset_week},
                                           'usageMetadata': {'account': {'id': 'acc-old'}}}},
            'antigravity': {'activeAccountId': 'acc-new',
                            'accounts': [{'id': 'acc-new', 'usage': {'status': 'error', 'updatedAt': now_ms, 'error': 'timeout'}}]},
        }}
        with patch.object(t, 'load_config', return_value=self.config), \
             patch.object(t, 'cli', return_value=mismatch_reply), \
             patch.object(t.antigravity_quota, 'probe', return_value=probe_ok) as probe_mock, \
             patch.object(t, 'save_json'):
            d1 = t.snapshot()
        probe_mock.assert_not_called()
        self.assertTrue(t.choose(d1, ag_only, 'STRONG', 'coder')['blocked'])
        # 2) Non-list buckets must block without falling back to aggregate or probe
        non_list_reply = {'ok': True, 'result': {
            'rateLimits': {'antigravity': {'status': 'ok', 'updatedAt': now_ms,
                                           'weekly': {'usedPercent': 5, 'windowMinutes': 10080, 'resetsAt': reset_week},
                                           'buckets': {'name': 123}}},
        }}
        with patch.object(t, 'load_config', return_value=self.config), \
             patch.object(t, 'cli', return_value=non_list_reply), \
             patch.object(t.antigravity_quota, 'probe', return_value=probe_ok) as probe_mock2, \
             patch.object(t, 'save_json'):
            d2 = t.snapshot()
        probe_mock2.assert_not_called()
        self.assertTrue(t.choose(d2, ag_only, 'STRONG', 'coder')['blocked'])

    def test_null_or_empty_buckets_and_contradictory_account_ids_block(self):
        now_ms = t.now().timestamp() * 1000
        reset_week = (t.now().timestamp() + 5 * 24 * 3600) * 1000
        probe_ok = {'status': 'ok', 'updated_at_ms': now_ms, 'windows': [],
                    'models': {'gemini-4-argon-medium': [{'window': 'session', 'used_percent': 11,
                                                          'resets_at': reset_week, 'window_minutes': 300}]}}
        ag_only = dict(self.config, candidates=[c for c in self.config['candidates'] if c['agent'] == 'antigravity'])
        # 1) Explicit null or [] buckets must block without falling back to aggregate or probe
        for bad_buckets in (None, []):
            for has_weekly in (True, False):
                rate = {'status': 'ok', 'updatedAt': now_ms, 'buckets': bad_buckets}
                if has_weekly:
                    rate['weekly'] = {'usedPercent': 5, 'windowMinutes': 10080, 'resetsAt': reset_week}
                with self.subTest(bad_buckets=bad_buckets, has_weekly=has_weekly), \
                     patch.object(t, 'load_config', return_value=self.config), \
                     patch.object(t, 'cli', return_value={'ok': True, 'result': {'rateLimits': {'antigravity': rate}}}), \
                     patch.object(t.antigravity_quota, 'probe', return_value=probe_ok) as pm, \
                     patch.object(t, 'save_json'):
                    d = t.snapshot()
                pm.assert_not_called()
                self.assertTrue(t.choose(d, ag_only, 'STRONG', 'coder')['blocked'])
        # 2) Cursor non-list buckets must also block rather than fall back to monthly total
        cursor_only = dict(self.config, candidates=[c for c in self.config['candidates'] if c['agent'] == 'cursor'])
        cur_reply = {'ok': True, 'result': {'rateLimits': {'cursor': {
            'status': 'ok', 'updatedAt': now_ms,
            'monthly': {'usedPercent': 3, 'windowMinutes': 43200, 'resetsAt': reset_week},
            'buckets': {'name': 'broken'},
        }}}}
        with patch.object(t, 'load_config', return_value=self.config), \
             patch.object(t, 'cli', return_value=cur_reply), \
             patch.object(t.antigravity_quota, 'probe', return_value={'status': 'unknown', 'windows': []}), \
             patch.object(t, 'save_json'):
            dc = t.snapshot()
        self.assertTrue(t.choose(dc, cursor_only, 'STANDARD', 'coder')['blocked'])
        # 3) Contradictory account IDs inside active usage or between account.id and readingAccount must block
        contradict_1 = {'ok': True, 'result': {
            'rateLimits': {'antigravity': {'status': 'ok', 'updatedAt': now_ms,
                                           'weekly': {'usedPercent': 5, 'windowMinutes': 10080, 'resetsAt': reset_week},
                                           'usageMetadata': {'account': {'id': 'acc-old'}}}},
            'antigravity': {'activeAccountId': 'acc-new', 'accounts': [{
                'id': 'acc-new', 'usage': {
                    'status': 'ok', 'updatedAt': now_ms,
                    'weekly': {'usedPercent': 5, 'windowMinutes': 10080, 'resetsAt': reset_week},
                    'usageMetadata': {'account': {'id': 'acc-old'}},
                },
            }]},
        }}
        contradict_2 = {'ok': True, 'result': {
            'rateLimits': {'antigravity': {'status': 'ok', 'updatedAt': now_ms,
                                           'weekly': {'usedPercent': 5, 'windowMinutes': 10080, 'resetsAt': reset_week},
                                           'usageMetadata': {'account': {'id': 'acc-new'},
                                                             'readingAccount': {'accountId': 'acc-old'}}}},
            'antigravity': {'activeAccountId': 'acc-new', 'accounts': [{'id': 'acc-new'}]},
        }}
        for reply in (contradict_1, contradict_2):
            with patch.object(t, 'load_config', return_value=self.config), \
                 patch.object(t, 'cli', return_value=reply), \
                 patch.object(t.antigravity_quota, 'probe', return_value=probe_ok) as pm, \
                 patch.object(t, 'save_json'):
                dm = t.snapshot()
            pm.assert_not_called()
            self.assertTrue(t.choose(dm, ag_only, 'STRONG', 'coder')['blocked'])
        # 4) '15h' label must not match '5h' session heuristic
        self.assertEqual(t._bucket_window_kind({'name': '15h limit'}), 'weekly')
        self.assertEqual(t._bucket_window_kind({'name': '5h limit'}), 'session')

    def test_legacy_claude_snapshot_and_missing_fable_window_are_safe(self):
        now_ms = t.now().timestamp() * 1000
        reset_week = (t.now().timestamp() + 2 * 24 * 3600) * 1000
        legacy_data = {
            'checked_at': t.now().isoformat(), 'codex_models': [],
            'providers': {'claude': {
                'status': 'ok', 'updated_at_ms': now_ms,
                'windows': [
                    {'window': 'weekly', 'used_percent': 20, 'window_minutes': 10080, 'resets_at': reset_week},
                    {'window': 'fableWeekly', 'used_percent': 100, 'window_minutes': 10080, 'resets_at': reset_week},
                ],
            }},
        }
        claude_only = dict(self.config, candidates=[
            {'agent': 'claude', 'model': 'sonnet', 'effort': None, 'origin': 'anthropic',
             'classes': ['STRONG'], 'roles': ['reviewer'], 'enabled': True},
            {'agent': 'claude', 'model': 'claude-fable-5-1', 'effort': None, 'origin': 'anthropic',
             'classes': ['STRONG'], 'roles': ['reviewer'], 'enabled': True},
        ])
        route = t.choose(legacy_data, claude_only, 'STRONG', 'reviewer')
        self.assertFalse(route['blocked'])
        self.assertEqual(route['model'], 'sonnet')
        # Missing fableWeekly must fail-safe (block Fable model, keep Sonnet allowed).
        no_fable_data = copy.deepcopy(legacy_data)
        no_fable_data['providers']['claude']['windows'] = [no_fable_data['providers']['claude']['windows'][0]]
        fable_only = dict(self.config, candidates=[claude_only['candidates'][1]])
        self.assertTrue(t.choose(no_fable_data, fable_only, 'STRONG', 'reviewer')['blocked'])

    def test_antigravity_partial_bucket_missing_group_blocks_and_name_split(self):
        now_ms = t.now().timestamp() * 1000
        reset_5h = (t.now().timestamp() + 3 * 3600) * 1000
        rate = {
            'status': 'ok', 'updatedAt': now_ms,
            'session': {'usedPercent': 10, 'windowMinutes': 300, 'resetsAt': reset_5h},
            'buckets': [
                {'name': 'Gemini Models · Weekly', 'usedPercent': 15, 'windowMinutes': 0, 'resetsAt': reset_5h},
                {'name': 123, 'usedPercent': 5},
            ],
        }
        with patch.object(t, 'load_config', return_value=self.config), \
             patch.object(t, 'cli', return_value={'ok': True, 'result': {'rateLimits': {'antigravity': rate}}}), \
             patch.object(t, 'save_json'):
            data = t.snapshot()
        neon = t.model_provider(data, {'agent': 'antigravity', 'model': 'gemini-4-neon-medium'})
        self.assertEqual([(w['window'], w['used_percent']) for w in neon['windows']], [('weekly', 15)])
        argon = t.model_provider(data, {'agent': 'antigravity', 'model': 'gemini-4-argon-medium'})
        self.assertEqual(argon['windows'], [])

    def test_unknown_quota_not_zero(self):
        self.data['providers']['codex']['windows']=[]
        self.assertTrue(t.choose(self.data,self.codex_only)['blocked'])

    def test_stale_provider_and_environment_rejected(self):
        self.data['providers']['codex']['updated_at_ms']-=16*60*1000
        self.assertTrue(t.choose(self.data,self.codex_only)['blocked'])
        self.data['checked_at']=(t.now()-dt.timedelta(hours=25)).isoformat()
        self.assertTrue(t.choose(self.data,self.codex_only,role='reviewer')['blocked'])

    def test_auth_expired(self):
        self.data['providers']['codex']['status']='error'
        self.assertTrue(t.choose(self.data,self.codex_only)['blocked'])

    def test_catalog_and_effort_are_required(self):
        self.data['codex_models']=[]
        self.assertTrue(t.choose(self.data,self.codex_only)['blocked'])
        self.setUp()
        for m in self.data['codex_models']: m['efforts']=[]
        self.assertTrue(t.choose(self.data,self.codex_only)['blocked'])

    def test_review_different_origin(self):
        result=t.choose(self.data,self.config,role='reviewer',exclude_origin='openai')
        self.assertNotEqual(result['origin'],'openai')
        for name in ('antigravity','cursor','claude'):
            self.data['providers'][name]['status']='error'
        self.assertTrue(t.choose(self.data,self.config,role='reviewer',exclude_origin='openai')['blocked'])

    def test_unavailable_assigned_candidate_falls_back(self):
        self.data['providers']['claude']['status']='error'
        result=t.choose(self.data,self.config,role='reviewer',pinned={'agent':'claude'})
        self.assertFalse(result['blocked'])
        self.assertNotEqual(result['agent'],'claude')
        self.assertEqual(result['assigned_unavailable']['assigned'],{'agent':'claude'})

    def test_expired_cursor_sign_in_falls_back_with_reason(self):
        self.data['providers']['cursor'].update(status='error',error='Cursor sign-in expired')
        result=t.choose(self.data,self.config,pinned={'agent':'cursor','model':'composer-2.5'})
        self.assertFalse(result['blocked'])
        self.assertNotEqual(result['agent'],'cursor')
        reasons=[r['reason'] for r in result['assigned_unavailable']['rejected']]
        self.assertIn('provider auth or quota unavailable: Cursor sign-in expired',reasons)

    def test_assigned_candidate_overrides_ranking(self):
        result=t.choose(self.data,self.config,pinned={'agent':'antigravity','model':'gemini-3.8-flash-medium'})
        self.assertEqual((result['agent'],result['model']),('antigravity','gemini-3.8-flash-medium'))

    def test_antigravity_quota_is_per_model(self):
        reset = (t.now() + dt.timedelta(hours=1)).isoformat()
        status={'userStatus':{'cascadeModelConfigData':{'clientModelConfigs':[
            {'modelId':'gemini-3.8-flash-high','quotaInfo':{'resetTime':reset}},
            {'modelId':'claude-sonnet-5-5-high','quotaInfo':{'remainingFraction':1,'resetTime':reset}}]}}}
        provider=antigravity_quota.parse_status(status,t.now().timestamp()*1000)
        self.assertEqual(provider['models']['gemini-3.8-flash-high'][0]['used_percent'],100)
        self.assertEqual(provider['models']['claude-sonnet-5-5-high'][0]['used_percent'],0)
        self.data['providers']['antigravity']=provider
        result=t.choose(self.data,self.config,role='reviewer',exclude_origin='openai')
        self.assertEqual((result['agent'],result['model']),('cursor','claude-opus-5-5-high'))
        rejected={r['model']:r['reason'] for r in result['rejected']}
        self.assertNotIn('provider auth', rejected['gemini-3.8-flash-high'])
        self.assertIn('claude-sonnet-5-5-high', {item['model'] for item in result['alternatives']})

    def test_antigravity_unreachable_is_unknown(self):
        self.assertEqual(antigravity_quota.parse_status({},1)['status'],'unknown')

    def test_kickoff_plan_task_routes_to_assigned_planner(self):
        task=t.read_json(FIX / 'plan-kickoff.json')
        t.task_spec(task)
        result=t.choose(self.data,self.config,task['class'],task['role'],pinned=task['assigned'])
        self.assertEqual((result['agent'],result['model']),('codex','gpt-6.1-sol'))

    def test_assigned_candidate_keeps_quota_gate(self):
        self.data['providers']['antigravity']['windows'][0]['used_percent']=99
        result=t.choose(self.data,self.config,pinned={'agent':'antigravity'})
        self.assertNotEqual(result.get('agent'),'antigravity')
        self.assertIn('assigned_unavailable',result)

    def test_max_requires_rationale(self):
        self.assertTrue(t.choose(self.data,self.config,'MAX',role='judge')['blocked'])
        self.assertFalse(t.choose(self.data,self.config,'MAX',role='judge',max_reason='Strong failed twice')['blocked'])

    def test_dry_run_does_not_call_cli(self):
        task=t.read_json(FIX / 'smoke.json')
        with patch.object(t,'cli') as mock:
            result=t.dispatch(task,t.choose(self.data,self.config),'example-run',False)
            self.assertTrue(result['dry_run']); mock.assert_not_called()

    def test_task_contract_missing_field(self):
        with self.assertRaises(ValueError): t.task_spec({'target':'x'})

    def test_failed_receipt_is_not_started_or_retried(self):
        task=t.read_json(FIX / 'smoke.json')
        with tempfile.TemporaryDirectory() as tmp, patch.object(t,'ROOT',Path(tmp)), patch.object(t,'cli',return_value={'ok':False,'outcome_unknown':True,'exit_code':1}) as mock:
            result=t.dispatch(task,t.choose(self.data,self.config),'example-run',True)
            self.assertFalse(result['started']); self.assertTrue(Path(result['receipt_path']).exists()); self.assertEqual(mock.call_count,1)

    def test_rpc_ok_failed_state_not_started(self):
        task=t.read_json(FIX / 'smoke.json')
        with tempfile.TemporaryDirectory() as tmp, patch.object(t,'ROOT',Path(tmp)), patch.object(t,'cli',return_value={'ok':True,'result':{'state':'failed'},'exit_code':0}) as mock:
            result=t.dispatch(task,t.choose(self.data,self.config),'example-run',True)
            self.assertFalse(result['started']); self.assertEqual(mock.call_count,1)

    def test_jev_missing_key_requires_coordinator(self):
        with patch.dict('os.environ',{},clear=True):
            answer=t.jev('classify-task','does-not-exist')
            self.assertTrue(answer['skipped']); self.assertTrue(answer['requires_coordinator_decision'])

    def test_present_unknown_upper_window_prevents_routing(self):
        for value in (None, 'unknown', 'missing'):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                catalog = root / 'models_cache.json'
                catalog.write_text(json.dumps({'models': [{'slug': 'gpt-6-luna',
                    'supported_reasoning_levels': [{'effort': 'medium'}]}]}), encoding='utf-8')
                upper = {} if value == 'missing' else {'usedPercent': value}
                accounts = {'ok': True, 'result': {'rateLimits': {'codex': {'status': 'ok',
                    'updatedAt': t.now().timestamp()*1000, 'session': {'usedPercent': 30}, 'weekly': upper}}}}
                with patch.object(t, 'ROOT', root), patch.dict('os.environ', {'CODEX_HOME': tmp}), \
                        patch.object(t, 'cli', side_effect=[accounts, {'ok': True, 'result': {}}]), \
                        patch.object(t, 'save_json'), patch.object(t.antigravity_quota, 'probe', return_value={'status': 'unknown', 'windows': []}):
                    data = t.snapshot()
                self.assertEqual(len(data['providers']['codex']['windows']), 2)
                self.assertTrue(t.choose(data, self.config)['blocked'])

    def test_orca_cli_resolution_respects_platform_and_managed_context(self):
        cases = [('linux', {}, 'orca-ide'), ('linux', {'ORCA_TERMINAL_HANDLE': 'real-handle'}, 'orca'),
                 ('win32', {}, 'orca'), ('darwin', {}, 'orca'),
                 ('linux', {'ORCA_DEV_REPO_ROOT': '/dev'}, 'orca-dev'),
                 ('linux', {'ORCA_CLI_COMMAND': '/explicit/orca', 'ORCA_DEV_REPO_ROOT': '/dev'}, '/explicit/orca')]
        for platform, env, expected in cases:
            with self.subTest(platform=platform, env=env), patch.dict('os.environ', env, clear=True), \
                    patch.object(t.sys, 'platform', platform):
                self.assertEqual(t.cli_command(), expected)

    def test_external_decision_rejects_future_and_naive_dates_without_launch(self):
        task = t.read_json(FIX / 'smoke.json') | {'external_dependency': True, 'decision_id': 'example'}
        config = self.config
        timestamps = [(t.now()+dt.timedelta(days=10)).isoformat(), '2026-09-30T12:00:00', 'invalid', None]
        for checked_at in timestamps:
            decision = {'example': {'checked_at': checked_at, 'sources': ['local: test'], 'impact': 'test'},
                        'routing-baseline': {'checked_at': t.now().isoformat(), 'sources': ['local: test'], 'impact': 'test'}}
            def read(path):
                path = str(path)
                return decision if path.endswith('EXTERNAL_DECISIONS.json') else config if path.endswith('ai-team.json') else task
            argv = ['team_control.py', 'start', '--task-file', 'task.json', '--run', 'test-run', '--execute']
            with self.subTest(checked_at=checked_at), patch.object(t.sys, 'argv', argv), \
                    patch.object(t, 'read_json', side_effect=read), patch.object(t, 'load_config', return_value=config), patch.object(t, 'snapshot', return_value=self.data), \
                    patch.object(t, 'cli') as launch, patch('builtins.print'):
                self.assertEqual(t.main(), 2)
                launch.assert_not_called()

    def test_internal_task_still_requires_fresh_routing_decision(self):
        task = t.read_json(FIX / 'smoke.json')
        config = self.config
        for record, blocked in [({}, True), ({'checked_at': (t.now()-dt.timedelta(hours=25)).isoformat(),
                'sources': ['local: test'], 'impact': 'test'}, True),
                ({'checked_at': t.now().isoformat(), 'sources': ['local: test'], 'impact': 'test'}, False)]:
            def read(path):
                path = str(path)
                return {'routing-baseline': record} if path.endswith('EXTERNAL_DECISIONS.json') else config if path.endswith('ai-team.json') else task
            argv = ['team_control.py', 'start', '--task-file', 'task.json', '--run', 'test-run']
            with self.subTest(record=record), patch.object(t.sys, 'argv', argv), \
                    patch.object(t, 'read_json', side_effect=read), patch.object(t, 'load_config', return_value=config), patch.object(t, 'snapshot', return_value=self.data), \
                    patch.object(t, 'cli') as launch, patch('builtins.print'):
                self.assertEqual(t.main(), 2 if blocked else 0)
                launch.assert_not_called()

class ProjectConfigTests(unittest.TestCase):
    def test_task_rules_replace_studio_wording(self):
        task = t.read_json(FIX/'smoke.json')
        spec = t.task_spec(task, ['Preserve existing addons and dist/.', 'Verify with Blender 5.2 only.'])
        self.assertIn('Preserve existing addons and dist/. Verify with Blender 5.2 only.', spec)
        self.assertNotIn('MASTER', spec)
        self.assertIn('absolute path', spec)

    def test_doctor_reads_checks_from_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            present = Path(tmp) / 'tool.exe'; present.write_text('x')
            config = {'doctor_checks': [{'name': 'tool', 'path': str(present)},
                                        {'name': 'missing', 'path': str(Path(tmp) / 'no.exe')},
                                        {'name': 'comfy', 'port': 1}]}
            with patch.object(t, 'cli', return_value={'result': {'runtime': {'state': 'ready', 'appVersion': '1'}}}):
                result = t.doctor(config)
        self.assertEqual(result['checks'], {'tool': True, 'missing': False, 'comfy': False})
        self.assertFalse(result['generation_started'])

    def test_pipeline_placeholder_without_pipeline_is_unknown(self):
        with patch.dict(sys.modules, {'scripts.pipeline_config': None}):
            self.assertIsNone(t.resolve_check_path('{pipeline:blender_exe}'))

    def test_jev_model_default_comes_from_config(self):
        argv = ['team_control.py', 'jev', '--mode', 'classify-task', '--state-file', 'x']
        with patch.object(t.sys, 'argv', argv), patch.object(t, 'load_config', return_value={'jev_model': 'jev-1.13.0'}), \
                patch.object(t, 'jev', return_value={'skipped': True}) as call, patch('builtins.print'):
            t.main()
        self.assertEqual(call.call_args.args[2], 'jev-1.13.0')

    def test_quota_bucket_from_config_wins_over_name(self):
        self.assertEqual(t.cursor_bucket_name({'model': 'grok-4.7-high', 'quota_bucket': 'Other Models'}), 'Other Models')
        self.assertEqual(t.cursor_bucket_name({'model': 'grok-4.7-high'}), 'Cursor Models')
        self.assertEqual(t.cursor_bucket_name({'model': 'composer-2.5'}), 'Cursor Models')
        self.assertEqual(t.cursor_bucket_name({'model': 'claude-opus-5-5-high'}), 'Other Models')

class BudgetV2Tests(unittest.TestCase):
    def setUp(self):
        self.targets=t.read_json(FIX / 'ai-team.json')['budget_targets']
        self.clock=1900000000
    def evaluate(self,windows,minutes=5,credits=None,recent=None,important=False):
        return evaluate_budget({'windows':windows,'banked_resets':credits or {}},self.targets,minutes,recent or [],'codex',important,self.clock)
    def window(self,name,usage,reset_minutes=30,duration=300):
        return {'window':name,'used_percent':usage,'resets_at':(self.clock+60*reset_minutes)*1000,'window_minutes':duration}
    def test_short_93_percent_allowed(self):
        self.assertFalse(self.evaluate([self.window('session',93)])['blocked'])
    def test_short_97_allows_short_but_refuses_long(self):
        self.assertFalse(self.evaluate([self.window('session',97)])['blocked'])
        self.assertTrue(self.evaluate([self.window('session',97)],minutes=30)['blocked'])
    def test_short_98_weekly95_monthly95_stop(self):
        for name,usage in [('session',98),('weekly',95),('monthly',95)]:
            self.assertTrue(self.evaluate([self.window(name,usage)])['blocked'])
    def test_upper_window_constrains_short(self):
        result=self.evaluate([self.window('session',20),self.window('weekly',92,1440,10080)])
        self.assertEqual(result['bottleneck'],'weekly')
        safe=self.evaluate([self.window('session',20),self.window('weekly',40,1440,10080)])
        self.assertLess(result['score'],safe['score'])
    def test_pace_and_expiry(self):
        result=self.evaluate([self.window('session',30,60)])
        state=result['windows'][0]
        self.assertAlmostEqual(state['period_progress'],.8)
        self.assertAlmostEqual(state['pace_delta'],-.5)
        later=self.evaluate([self.window('session',30,240)])
        self.assertGreater(result['score'],later['score'])
    def test_monthly_burn_ahead_is_penalized(self):
        over=self.evaluate([self.window('monthly',55,30240,43200)])
        steady=self.evaluate([self.window('monthly',20,30240,43200)])
        self.assertGreater(over['windows'][0]['target_pace_delta'],0)
        self.assertLess(over['score'],steady['score'])
    def test_diversity_small_tie_penalty(self):
        normal=self.evaluate([self.window('session',30)])
        repeat=self.evaluate([self.window('session',30)],recent=['codex']*5)
        self.assertAlmostEqual(normal['score']-repeat['score'],1.25)
    def test_unknown_pace_is_not_fabricated(self):
        result=self.evaluate([{'window':'weekly','used_percent':40}])
        self.assertIsNone(result['windows'][0]['period_progress'])
        self.assertIsNone(result['windows'][0]['time_to_reset_min'])
    def test_reset_passed_and_invalid_percent(self):
        self.assertTrue(self.evaluate([self.window('session',5,-1)])['blocked'])
        self.assertTrue(self.evaluate([self.window('session',-1)])['blocked'])
    def test_ticket_advice_not_automatic_action(self):
        credits={'available_count':2,'credits':[{'status':'available','expires_at':(self.clock+3600)*1000},
            {'status':'available','expires_at':(self.clock-3600)*1000}]}
        result=self.evaluate([self.window('session',96,60),self.window('weekly',89,1440,10080)],credits=credits,important=True)
        self.assertEqual(result['banked_reset_count'],1)
        self.assertTrue(result['reset_review_recommended'])
        self.assertEqual(result['reset_action'],'none')
    def test_ticket_cannot_override_hard_stop(self):
        credits={'available_count':3,'next_expires_at':(self.clock+3600)*1000}
        self.assertTrue(self.evaluate([self.window('session',98)],credits=credits)['blocked'])

    def test_full_use_policy_runs_until_exhausted(self):
        """hard_stop 1.0: keep the chosen AI until its quota is really gone (no early hand-off)."""
        full={'short_window':{'target':.93,'hard_stop':1.0},'weekly':{'target':.88,'hard_stop':1.0},
              'monthly':{'target':.83,'hard_stop':1.0},'reserve':{'weekly':0,'monthly':0}}
        provider={'windows':[self.window('session',97,60),self.window('weekly',99,1440,10080)]}
        result=evaluate_budget(provider,full,30,[],'codex',False,self.clock)
        self.assertFalse(result['blocked'])
        provider={'windows':[self.window('weekly',100,1440,10080)]}
        self.assertTrue(evaluate_budget(provider,full,30,[],'codex',False,self.clock)['blocked'])

class ReadOnlySnapshotTests(unittest.TestCase):
    def test_snapshot_no_save_leaves_runtime_absent(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(t, 'ROOT', Path(tmp)), \
                patch.object(t, 'cli', return_value={'ok': True, 'result': {}}), \
                patch.object(t.antigravity_quota, 'probe', return_value={'status': 'unknown', 'windows': []}):
            t.snapshot(save=False)
            self.assertFalse((Path(tmp) / '.ai/runtime').exists())


class ApprovalGateCliTests(unittest.TestCase):
    def setUp(self):
        self.config = t.read_json(FIX / 'ai-team.json')
        self.data = {
            'checked_at': t.now().isoformat(),
            'codex_models': [{'model': c['model'], 'efforts': ['medium']} for c in self.config['candidates'] if c['agent'] == 'codex'],
            'providers': {
                name: {'status': 'ok', 'updated_at_ms': t.now().timestamp() * 1000, 'windows': [{'used_percent': 10}]}
                for name in ('codex', 'claude', 'cursor', 'antigravity')
            },
        }
        self.decisions = {'routing-baseline': {'checked_at': t.now().isoformat(), 'sources': ['local: test'], 'impact': 'ok'}}

    def _run_start(self, task, execute=True):
        def read(path):
            s = str(path)
            return self.decisions if s.endswith('EXTERNAL_DECISIONS.json') else self.config if s.endswith('ai-team.json') else task
        argv = ['team_control.py', 'start', '--task-file', 'task.json', '--run', 'run_test'] + (['--execute'] if execute else [])
        out = []
        with tempfile.TemporaryDirectory() as tmp, patch.object(t, 'ROOT', Path(tmp)), \
                patch.object(t.sys, 'argv', argv), patch.object(t, 'read_json', side_effect=read), \
                patch.object(t, 'load_config', return_value=self.config), patch.object(t, 'snapshot', return_value=self.data), \
                patch.object(t, 'cli', return_value={'ok': True, 'exit_code': 0, 'result': {'state': 'ready', 'dispatchId': 'ctx_1'}}) as launch, \
                patch('builtins.print', side_effect=lambda *a, **kw: out.append(' '.join(map(str, a)))):
            code = t.main()
        return code, json.loads('\n'.join(out)), launch

    def test_start_execute_blocks_without_user_approval(self):
        task = t.read_json(FIX / 'smoke.json')
        dry_code, dry_res, dry_launch = self._run_start(task, execute=False)
        self.assertEqual(dry_code, 0)
        self.assertTrue(dry_res['approval_required'])
        self.assertFalse(dry_res['approval_ready'])
        dry_launch.assert_not_called()

        code, res, launch = self._run_start(task, execute=True)
        self.assertEqual(code, 2)
        self.assertTrue(res['blocked'])
        self.assertFalse(res['started'])
        self.assertTrue(res['approval_required'])
        launch.assert_not_called()

    def test_start_execute_blocks_escalated_reviewer_without_upgrade_approved(self):
        base = dict(t.read_json(FIX / 'smoke.json'), role='reviewer')
        base['class'] = 'STANDARD'
        base['approval'] = {
            'at': '2026-11-17T23:45+09:00',
            'user_words': '2026-11-17 user approved reviewer',
            'models': [{'agent': 'codex', 'model': 'gpt-6-astra', 'origin': 'openai'}],
        }
        code, res, launch = self._run_start(base, execute=True)
        self.assertEqual(code, 2)
        self.assertTrue(res['blocked'])
        launch.assert_not_called()

        base['approval']['upgrade_approved'] = True
        code2, res2, launch2 = self._run_start(base, execute=True)
        self.assertEqual(code2, 0)
        self.assertTrue(res2['started'])
        self.assertGreaterEqual(launch2.call_count, 1)

    def test_start_execute_blocks_max_without_max_approved(self):
        task = dict(t.read_json(FIX / 'smoke.json'), role='judge', max_reason='Strong inconclusive',
                    approval={'at': '2026-11-17T23:45+09:00', 'user_words': '2026-11-17 user ok',
                              'models': [{'agent': 'codex', 'model': 'gpt-6-astra', 'origin': 'openai'}]})
        task['class'] = 'MAX'
        code, res, launch = self._run_start(task, execute=True)
        self.assertEqual(code, 2)
        self.assertTrue(res['blocked'])
        launch.assert_not_called()

        task['approval']['max_approved'] = True
        code2, res2, launch2 = self._run_start(task, execute=True)
        self.assertEqual(code2, 0)
        self.assertTrue(res2['started'])
        self.assertGreaterEqual(launch2.call_count, 1)

    def test_start_execute_succeeds_with_matching_approval(self):
        task = dict(t.read_json(FIX / 'smoke.json'), role='coder',
                    approval={'at': '2026-11-17T23:45+09:00', 'user_words': '2026-11-17 user ok',
                              'models': [{'agent': 'codex', 'model': 'gpt-6-luna', 'origin': 'openai'}]})
        code, res, launch = self._run_start(task, execute=True)
        self.assertEqual(code, 0)
        self.assertTrue(res['started'])
        self.assertGreaterEqual(launch.call_count, 1)

    def test_workflow_cli_approval_fields_match_start_gating(self):
        def run_wf(task_obj):
            out = []
            with patch.object(t.sys, 'argv', ['team_control.py', 'workflow', '--task-file', 'task.json']), \
                    patch.object(t, 'read_json', return_value=task_obj), \
                    patch('builtins.print', side_effect=lambda *a, **kw: out.append(' '.join(map(str, a)))):
                code = t.main()
            return code, json.loads('\n'.join(out))

        smoke = t.read_json(FIX / 'smoke.json')
        c0, r0 = run_wf(smoke)
        self.assertEqual(c0, 0)
        self.assertFalse(r0['approval_recorded'])
        self.assertIs(r0['approval_ready'], False)
        self.assertTrue(r0['approval_missing'])

        esc_no_flag = dict(smoke, role='reviewer', approval={
            'at': '2026-11-17T23:45+09:00', 'user_words': 'ok',
            'models': [{'agent': 'codex', 'model': 'gpt-6-astra', 'origin': 'openai'}]})
        esc_no_flag['class'] = 'STANDARD'
        _, r1 = run_wf(esc_no_flag)
        self.assertFalse(r1['approval_recorded'])
        self.assertIs(r1['approval_ready'], False)
        self.assertTrue(r1['escalated'])
        self.assertEqual(r1['expected_class'], 'STRONG')

        esc_ok = copy.deepcopy(esc_no_flag)
        esc_ok['approval']['upgrade_approved'] = True
        _, r2 = run_wf(esc_ok)
        self.assertTrue(r2['approval_recorded'])
        self.assertIsNone(r2['approval_ready'])
        self.assertEqual(r2['approval_missing'], [])

        max_no_flag = dict(esc_no_flag, role='judge')
        max_no_flag['class'] = 'MAX'
        _, r3 = run_wf(max_no_flag)
        self.assertFalse(r3['approval_recorded'])
        self.assertIs(r3['approval_ready'], False)

        bad_origin_task = dict(smoke, role='coder', approval={
            'at': '2026-11-17T23:45+09:00', 'user_words': 'ok',
            'models': [{'agent': 'codex', 'model': 'gpt-6-luna', 'origin': 'codex'}]})
        with patch.object(t, 'load_config', return_value=self.config):
            _, r4 = run_wf(bad_origin_task)
        self.assertFalse(r4['approval_recorded'])
        self.assertIs(r4['approval_ready'], False)
        self.assertTrue(any('origin' in m for m in r4['approval_missing']))


class PreflightGateTests(unittest.TestCase):
    def setUp(self):
        self.config = t.read_json(FIX / 'ai-team.json')
        now_ms = t.now().timestamp() * 1000
        reset_week = (t.now().timestamp() + 5 * 24 * 3600) * 1000
        reset_5h = (t.now().timestamp() + 3 * 3600) * 1000
        self.data = {
            'checked_at': t.now().isoformat(),
            'codex_models': [
                {'model': 'gpt-6.2-astra', 'efforts': ['low', 'medium', 'high']},
                {'model': 'gpt-6.2-sol', 'efforts': ['low', 'medium', 'high']},
            ],
            'providers': {
                'codex': {'status': 'ok', 'updated_at_ms': now_ms, 'windows': [
                    {'window': 'session', 'used_percent': 20, 'window_minutes': 300, 'resets_at': reset_5h},
                    {'window': 'weekly', 'used_percent': 25, 'window_minutes': 10080, 'resets_at': reset_week},
                ]},
                'cursor': {'status': 'ok', 'updated_at_ms': now_ms, 'windows': [
                    {'window': 'monthly', 'used_percent': 100, 'window_minutes': 43200, 'resets_at': reset_week},
                ], 'models': {
                    'grok-4.7-high': [{'window': 'monthly', 'used_percent': 60, 'window_minutes': 43200, 'resets_at': reset_week}],
                }},
                'antigravity': {'status': 'ok', 'updated_at_ms': now_ms, 'windows': [], 'models': {},
                                'buckets_present': True, 'bucket_groups': {
                                    'Gemini Models': [{'window': 'weekly', 'used_percent': 15, 'window_minutes': 10080, 'resets_at': reset_week}],
                                    'Claude and GPT models': [{'window': 'weekly', 'used_percent': 100, 'window_minutes': 10080, 'resets_at': reset_week}],
                                }},
            },
            'recent_providers': [],
        }
        self.fresh_decisions = {
            'routing-baseline': {'checked_at': t.now().isoformat(), 'sources': ['local: test'], 'impact': 'test'},
        }

    def _run_preflight(self, task, extra_args, decisions=None, data=None):
        decs = self.fresh_decisions if decisions is None else decisions
        snap = self.data if data is None else data
        out = []
        argv = ['team_control.py', 'preflight', '--task-file', 'task.json', *extra_args]
        def fake_read(path):
            p = str(path)
            if p.endswith('EXTERNAL_DECISIONS.json'):
                return decs
            return task
        with patch.object(t.sys, 'argv', argv), \
             patch.object(t, 'read_json', side_effect=fake_read), \
             patch.object(t, 'load_config', return_value=self.config), \
             patch.object(t, 'snapshot', return_value=snap), \
             patch('builtins.print', side_effect=lambda *a, **kw: out.append(' '.join(map(str, a)))):
            code = t.main()
        return code, json.loads('\n'.join(out))

    def test_preflight_blocks_without_approval_and_passes_with_approval(self):
        task = dict(t.read_json(FIX / 'smoke.json'), role='reviewer', **{'class': 'STRONG'})
        code, res = self._run_preflight(task, ['--agent', 'codex', '--model', 'gpt-6.2-astra', '--effort', 'medium', '--run', 'run_1'])
        self.assertEqual(code, 2)
        self.assertTrue(res['blocked'])
        self.assertTrue(res['approval_required'])

        approved = dict(task, approval={
            'at': '2026-11-23T20:00+09:00', 'user_words': 'ok',
            'models': [{'agent': 'codex', 'model': 'gpt-6.2-astra', 'origin': 'openai'}],
        })
        code2, res2 = self._run_preflight(approved, ['--agent', 'codex', '--model', 'gpt-6.2-astra', '--effort', 'medium', '--run', 'run_1'])
        self.assertEqual(code2, 0)
        self.assertTrue(res2['ok'])
        self.assertFalse(res2['blocked'])
        self.assertIn('worker-start', res2['recommended_command'])
        self.assertIn('--model', res2['recommended_command'])

    def test_preflight_supports_unlisted_antigravity_bucket_model(self):
        task = dict(t.read_json(FIX / 'smoke.json'), role='reviewer', **{'class': 'STRONG'}, approval={
            'at': '2026-11-23T20:00+09:00', 'user_words': 'ok',
            'models': [{'agent': 'antigravity', 'model': 'gemini-4-neon-medium', 'origin': 'google'}],
        })
        code, res = self._run_preflight(task, ['--agent', 'antigravity', '--model', 'gemini-4-neon-medium'])
        self.assertEqual(code, 0)
        self.assertTrue(res['ok'])
        self.assertEqual(res['route']['origin'], 'google')
        self.assertEqual(res['used_percent'], 15)

    def test_preflight_blocks_cursor_effort_and_fast_variant(self):
        task = dict(t.read_json(FIX / 'smoke.json'), role='reviewer', **{'class': 'STRONG'}, approval={
            'at': '2026-11-23T20:00+09:00', 'user_words': 'ok',
            'models': [{'agent': 'cursor', 'model': 'grok-4.7-high', 'origin': 'xai'}],
        })
        code, res = self._run_preflight(task, ['--agent', 'cursor', '--model', 'grok-4.7-high', '--effort', 'high'])
        self.assertEqual(code, 2)
        self.assertTrue(res['blocked'])
        code2, res2 = self._run_preflight(task, ['--agent', 'cursor', '--model', 'grok-4.7-fast'])
        self.assertEqual(code2, 2)
        self.assertTrue(res2['blocked'])

    def test_preflight_enforces_freshness_origin_and_confidential_gates(self):
        task = dict(t.read_json(FIX / 'smoke.json'), role='reviewer', exclude_origin='openai', **{'class': 'STRONG'}, approval={
            'at': '2026-11-23T20:00+09:00', 'user_words': 'ok',
            'models': [{'agent': 'codex', 'model': 'gpt-6.2-astra', 'origin': 'openai'}],
        })
        code, res = self._run_preflight(task, ['--agent', 'codex', '--model', 'gpt-6.2-astra', '--effort', 'medium'])
        self.assertEqual(code, 2)
        self.assertIn('same model origin', res['reason'])

        task_stale = dict(task, exclude_origin='google')
        code_stale, res_stale = self._run_preflight(task_stale, ['--agent', 'codex', '--model', 'gpt-6.2-astra', '--effort', 'medium'], decisions={})
        self.assertEqual(code_stale, 2)
        self.assertIn('Freshness Gate', res_stale['reason'])

        task_conf = dict(task_stale, context={'classification': 'confidential', 'read_files': []})
        code_conf, res_conf = self._run_preflight(task_conf, ['--agent', 'codex', '--model', 'gpt-6.2-astra', '--effort', 'medium'])
        self.assertEqual(code_conf, 2)
        self.assertTrue(res_conf['blocked'])

    def test_preflight_blocks_unapproved_escalation_and_max(self):
        task = dict(t.read_json(FIX / 'smoke.json'), role='reviewer', **{'class': 'STANDARD'}, approval={
            'at': '2026-11-23T20:00+09:00', 'user_words': 'ok',
            'models': [{'agent': 'codex', 'model': 'gpt-6.2-astra', 'origin': 'openai'}],
        })
        code, res = self._run_preflight(task, ['--agent', 'codex', '--model', 'gpt-6.2-astra', '--effort', 'medium'])
        self.assertEqual(code, 2)
        self.assertTrue(res['escalated'])
        self.assertTrue(res['blocked'])

        max_task = dict(task, **{'class': 'MAX', 'max_reason': 'final audit'})
        code_max, res_max = self._run_preflight(max_task, ['--agent', 'codex', '--model', 'gpt-6.2-astra', '--effort', 'medium'])
        self.assertEqual(code_max, 2)
        self.assertTrue(res_max['blocked'])

    def test_preflight_hardening_against_origin_spoof_role_limit_cursor_codex_and_bad_decisions(self):
        base = dict(t.read_json(FIX / 'smoke.json'), role='reviewer', **{'class': 'STRONG'}, approval={
            'at': '2026-11-23T20:00+09:00', 'user_words': 'ok',
            'models': [
                {'agent': 'codex', 'model': 'gpt-6.2-astra', 'origin': 'openai'},
                {'agent': 'cursor', 'model': 'claude-fable-5-1-high', 'origin': 'anthropic'},
                {'agent': 'cursor', 'model': 'gpt-6.2-sol', 'origin': 'openai'},
            ],
        })
        # 1) Explicit --origin contradicting known model origin must be blocked
        code, res = self._run_preflight(base, ['--agent', 'codex', '--model', 'gpt-6.2-astra', '--effort', 'medium', '--origin', 'google'])
        self.assertEqual(code, 2)
        self.assertIn('contradicts', res['reason'])
        # 2) Non-review role (coder) must be blocked by read-only preflight
        coder_task = dict(base, role='coder')
        code2, res2 = self._run_preflight(coder_task, ['--agent', 'codex', '--model', 'gpt-6.2-astra', '--effort', 'medium'])
        self.assertEqual(code2, 2)
        self.assertIn('read-only', res2['reason'])
        # 3) MAX-only registered candidate cannot run under STRONG
        code3, res3 = self._run_preflight(base, ['--agent', 'cursor', '--model', 'claude-fable-5-1-high'])
        self.assertEqual(code3, 2)
        self.assertTrue(res3['blocked'])
        # 4) Cursor GPT model blocked by cursor_policy
        code4, res4 = self._run_preflight(base, ['--agent', 'cursor', '--model', 'gpt-6.2-sol'])
        self.assertEqual(code4, 2)
        self.assertIn('cursor_policy', res4['reason'])
        # 5) Codex missing/empty effort blocked (also case-insensitive agent normalization)
        code5, res5 = self._run_preflight(base, ['--agent', 'Codex', '--model', 'gpt-6.2-astra'])
        self.assertEqual(code5, 2)
        self.assertIn('effort', res5['reason'])
        # 6) Malformed EXTERNAL_DECISIONS (boolean sources/impact or null record) blocked cleanly
        for bad in ({'routing-baseline': None}, {'routing-baseline': {'checked_at': t.now().isoformat(), 'sources': True, 'impact': True}}):
            code6, res6 = self._run_preflight(base, ['--agent', 'codex', '--model', 'gpt-6.2-astra', '--effort', 'medium'], decisions=bad)
            self.assertEqual(code6, 2)
            self.assertIn('Freshness Gate', res6['reason'])
        # 7) --write-spec-file writes verified spec and binds sha256 + command (exact bytes on Windows)
        with tempfile.TemporaryDirectory() as tmp:
            import hashlib
            spec_out = Path(tmp) / 'verified.spec.txt'
            code7, res7 = self._run_preflight(base, ['--agent', 'codex', '--model', 'gpt-6.2-astra', '--effort', 'medium', '--write-spec-file', str(spec_out)])
            self.assertEqual(code7, 0)
            self.assertTrue(spec_out.exists())
            raw = spec_out.read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), res7['spec_sha256'])
            self.assertIn('--spec-file', res7['recommended_command'])
            self.assertIn('Read-only review mode:', raw.decode('utf-8'))
            self.assertIn('Do not read repository-wide state', raw.decode('utf-8'))
        # 8) Single-sided Cursor bucket at 100% blocks its models (never falls back to 10% aggregate)
        now_ms = t.now().timestamp() * 1000
        reset_week = (t.now().timestamp() + 5 * 24 * 3600) * 1000
        cur_one_side = {'ok': True, 'result': {'rateLimits': {'cursor': {
            'status': 'ok', 'updatedAt': now_ms,
            'monthly': {'usedPercent': 10, 'windowMinutes': 43200, 'resetsAt': reset_week},
            'buckets': [{'name': 'Other Models', 'usedPercent': 100, 'windowMinutes': 43200, 'resetsAt': reset_week}],
        }}}}
        with patch.object(t, 'load_config', return_value=self.config), \
             patch.object(t, 'cli', return_value=cur_one_side), \
             patch.object(t.antigravity_quota, 'probe', return_value={'status': 'unknown', 'windows': []}), \
             patch.object(t, 'save_json'):
            d_one = t.snapshot()
        unlisted_claude = dict(base, approval={
            'at': '2026-11-23T20:00+09:00', 'user_words': 'ok',
            'models': [{'agent': 'cursor', 'model': 'claude-opus-5-6-high', 'origin': 'anthropic'}],
        })
        code8, res8 = self._run_preflight(unlisted_claude, ['--agent', 'cursor', '--model', 'claude-opus-5-6-high'], data=d_one)
        self.assertEqual(code8, 2)
        self.assertTrue(res8['blocked'])


if __name__=='__main__': unittest.main()
