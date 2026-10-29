"""Search limits/checkpoint/quality regressions with a synthetic battle oracle."""
from pathlib import Path
import os
import tempfile
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from experience import plan_key
from search_policy import search
from autoplay import Runner,main,verified
from live_roster import LiveReadError
from model import read_json,write_json
from test_tactics import fixture
from job_status import search_limits,search_summary,autoplay_summary


class Oracle:
    def __init__(self):
        sim,self.stage,_=fixture();self.__dict__.update(sim.__dict__)
        self.capture=dict(captured_at='test');self.attribute_validation={};self.calls=[];self.elapsed=0
        self.answer=lambda rows,seed:(False,1)
        self.after=lambda:None
    def evaluate(self,stage,rows,seed,trace=False):
        self.calls.append((plan_key(rows),seed));self.elapsed+=1;self.after()
        won,score=self.answer(rows,seed)
        return dict(won=won,score=score,kills=10 if won else 3,total_enemies=10,battle_secs=20,seed=seed)


class SearchSessionTests(unittest.TestCase):
    def test_default_review_only_adds_one_simulation(self):
        sim=Oracle();sim.answer=lambda rows,seed:(True,100)
        result=search(sim,sim.stage,budget=10,stop_when_verified=True)
        self.assertEqual([seed for _,seed in sim.calls],[123456,701])
        self.assertEqual(result['review_mode'],'light');self.assertTrue(verified(result))

    def test_disabled_review_accepts_training_winner_without_extra_simulations(self):
        sim=Oracle();sim.answer=lambda rows,seed:(True,100)
        result=search(sim,sim.stage,budget=10,stop_when_verified=True,review_mode='none')
        self.assertEqual([seed for _,seed in sim.calls],[123456]);self.assertTrue(verified(result))
        self.assertEqual(result['finalists'][0]['validation'],[])
        self.assertIn('关闭',search_summary(result))

    def test_full_review_retains_all_seed_and_order_combinations(self):
        from search_session import order_samples
        sim=Oracle();sim.answer=lambda rows,seed:(True,100)
        result=search(sim,sim.stage,budget=10,stop_when_verified=True,review_mode='full')
        expected=[(plan_key(rows),seed) for _,rows in order_samples(result['placements'],True) for seed in (701,2029,8191)]
        self.assertEqual(sim.calls[1:],expected);self.assertTrue(verified(result))

    def test_light_review_failure_does_not_deploy_or_stop_as_success(self):
        sim=Oracle();sim.answer=lambda rows,seed:(seed==123456,100)
        result=search(sim,sim.stage,budget=1,stop_when_verified=True)
        self.assertEqual(result['status'],'no_solution');self.assertFalse(verified(result))
        self.assertEqual(result['stop_reason'],'candidate_limit')

    def test_resume_rejects_changed_review_mode(self):
        with tempfile.TemporaryDirectory() as folder:
            checkpoint=Path(folder)/'result.checkpoint.json';sim=Oracle()
            search(sim,sim.stage,budget=1,checkpoint=checkpoint)
            with self.assertRaisesRegex(ValueError,'复核设置不一致'):
                search(sim,sim.stage,budget=1,resume=checkpoint,review_mode='none')

    def test_reusing_current_formation_respects_review_mode(self):
        for mode,seeds in (('light',[123456,701]),('none',[123456]),('full',[123456,701,2029,8191])):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as folder:
                sim=Oracle();sim.answer=lambda rows,seed:(True,100);sim.capture['shared_level']=235
                runner=Runner.__new__(Runner);runner.review_mode=mode;runner.stop_when_verified=True
                runner.catalog=SimpleNamespace(stage=lambda _:sim.stage);runner.folder=Path(folder)
                runner.event=lambda *args,**kw:None;runner.compute_stopped=lambda:False
                memory=SimpleNamespace(record=lambda *args:None,close=lambda:None)
                state=dict(current_stage_id=1,request_order=[dict(unit_id=1,x=1,y=2),dict(unit_id=2,x=2,y=2)])
                with patch('live_roster.read_live',return_value=sim.capture),patch('live_roster.to_roster'),\
                    patch('combat.Simulator',return_value=sim),patch('experience.Experience',return_value=memory):
                    result=runner.plan(state)
                self.assertEqual([seed for _,seed in sim.calls],seeds);self.assertTrue(verified(result))

    def test_search_cli_passes_review_choice_to_the_search(self):
        from search_policy import main as search_main
        for choice in (None,'none','full'):
            with self.subTest(choice=choice),tempfile.TemporaryDirectory() as folder:
                path=Path(folder);write_json(path/'capture.json',{})
                sim=Oracle();sim.answer=lambda rows,seed:(True,100)
                catalog=SimpleNamespace(stages=[dict(id=1,name='1-1')],stage=lambda _:sim.stage)
                args=['search','--capture',str(path/'capture.json'),'--stage','1-1','--budget','1',
                    '--stop-on-success','--no-experience','--out',str(path/'result.json')]
                if choice:args+=['--review',choice]
                with patch('sys.argv',args),patch('search_policy.Simulator',return_value=sim),\
                    patch('search_policy.Catalog',return_value=catalog),patch('builtins.print'):
                    search_main()
                result=read_json(path/'result.json')
                self.assertEqual(result['review_mode'],choice or 'light');self.assertTrue(verified(result))

    def test_time_limit_stops_without_an_extra_replay(self):
        sim=Oracle();result=search(sim,sim.stage,budget=0,max_seconds=3,clock=lambda:sim.elapsed)
        self.assertEqual(result['stop_reason'],'time_limit');self.assertEqual(len(sim.calls),3)
        self.assertEqual(result['status'],'no_solution');self.assertIn('evaluation',result)

    def test_deadline_during_validation_cannot_mark_partial_checks_as_verified(self):
        sim=Oracle();sim.answer=lambda rows,seed:(True,100)
        result=search(sim,sim.stage,budget=0,max_seconds=3,clock=lambda:sim.elapsed,robust_orders=True)
        self.assertEqual(len(sim.calls),3);self.assertFalse(verified(result))
        self.assertFalse(result['finalists'][0]['validation_complete'])

    def test_stop_saves_best_and_resume_explores_new_candidates(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder);checkpoint=path/'search.checkpoint.json';stop=path/'STOP';sim=Oracle()
            sim.after=lambda:stop.touch() if len(sim.calls)==3 else None
            first=search(sim,sim.stage,budget=0,stop_path=stop,checkpoint=checkpoint)
            self.assertEqual(first['status'],'cancelled');self.assertTrue(checkpoint.exists())
            stop.unlink();next_sim=Oracle()
            second=search(next_sim,next_sim.stage,budget=3,resume=checkpoint,checkpoint=checkpoint)
            self.assertEqual(second['run_evaluated'],3);self.assertEqual(second['evaluated'],6)
            self.assertFalse({k for k,s in sim.calls}&{k for k,s in next_sim.calls})
            next_sim.rows[1]['gs']=900
            with self.assertRaisesRegex(ValueError,'不一致'):
                search(next_sim,next_sim.stage,budget=1,resume=checkpoint)

    def test_slow_stable_winner_beats_fast_seed_specific_winners(self):
        sim=Oracle()
        def answer(rows,seed):
            stable=3 in [p['unit_id'] for p in rows]
            return (stable or seed==123456),90 if stable else 100 if seed==123456 else 0
        sim.answer=answer
        result=search(sim,sim.stage,budget=12)
        self.assertTrue(verified(result));self.assertIn(3,[p['unit_id'] for p in result['placements']])

    def test_all_single_pet_replacements_are_considered_without_a_power_cutoff(self):
        sim=Oracle();sim.rows[3]['gs']=1
        initial=[dict(unit_id=1,x=1,y=2),dict(unit_id=2,x=2,y=2)]
        result=search(sim,sim.stage,budget=12,initial_plan=initial)
        self.assertEqual(result['replacement_checked'],result['replacement_total'])
        seen={key for key,seed in sim.calls}
        for i in range(2):
            variant=[dict(p) for p in initial];variant[i]['unit_id']=3
            self.assertIn(plan_key(variant),seen)

    def test_early_success_and_overnight_limits_are_explicit(self):
        sim=Oracle();sim.answer=lambda rows,seed:(True,100)
        result=search(sim,sim.stage,budget=0,max_seconds=8*3600,stop_when_verified=True)
        self.assertEqual(result['stop_reason'],'verified');self.assertEqual(result['evaluated'],1)
        self.assertTrue(verified(result))
        self.assertEqual(search_limits('0','480'),(0,28800))
        for invalid in ('nan','inf','-1'):
            with self.assertRaises(ValueError):search_limits('0',invalid)

    def test_systematic_sweep_restarts_from_an_improved_formation(self):
        sim=Oracle();sim.answer=lambda rows,seed:(False,sum(p['unit_id'] for p in rows))
        initial=[dict(unit_id=1,x=1,y=2),dict(unit_id=2,x=2,y=2)]
        result=search(sim,sim.stage,budget=30,initial_plan=initial)
        self.assertGreaterEqual(result['replacement_round'],2)

    def test_resume_can_reuse_a_completed_validation_without_repeating_simulations(self):
        with tempfile.TemporaryDirectory() as folder:
            checkpoint=Path(folder)/'result.checkpoint.json';sim=Oracle();sim.answer=lambda rows,seed:(True,100)
            search(sim,sim.stage,budget=10,stop_when_verified=True,checkpoint=checkpoint)
            next_sim=Oracle()
            result=search(next_sim,next_sim.stage,budget=10,stop_when_verified=True,resume=checkpoint)
            self.assertEqual(next_sim.calls,[]);self.assertEqual(result['run_evaluated'],0)
            self.assertTrue(verified(result))

    def test_status_explains_no_solution_and_keeps_object_error(self):
        text=search_summary(dict(status='no_solution',reason='达到搜索时长上限',run_elapsed_seconds=28800,
            run_evaluated=5000,budget=0,validation_wins=2,validation_total=3))
        self.assertIn('未找到',text);self.assertIn('08:00:00',text);self.assertIn('2/3',text)
        self.assertIn('对象不唯一',autoplay_summary(dict(event='stopped',reason='对象不唯一')))

    def test_panel_keeps_actual_worker_failure_instead_of_only_a_log_path(self):
        from panel import MainlinePanel
        with tempfile.TemporaryDirectory() as folder:
            app=MainlinePanel.__new__(MainlinePanel);app.autoplay_run_dir=Path(folder)
            app.autoplay_log=(app.autoplay_run_dir/'run.log').open('w',encoding='utf-8')
            app.autoplay_process=SimpleNamespace(returncode=1,poll=lambda:1)
            write_json(app.autoplay_run_dir/'status.json',dict(event='stopped',reason='当前有效布阵对象不唯一',reason_code='game_state_error'))
            received=[];app.set_job_status=lambda value,**kw:received.append(value)
            app.poll_autoplay()
            self.assertEqual(len(received),1);self.assertIn('对象不唯一',received[0]['reason'])

    def test_panel_preserves_best_on_no_solution_but_does_not_apply_cancelled_results(self):
        from panel import MainlinePanel
        for state in ('no_solution','cancelled'):
            with self.subTest(state=state),tempfile.TemporaryDirectory() as folder:
                app=MainlinePanel.__new__(MainlinePanel);path=Path(folder)
                app.combat_output=path/'result.json';app.combat_log=(path/'run.log').open('w',encoding='utf-8')
                app.combat_process=SimpleNamespace(returncode=0,poll=lambda:0)
                app.stage_data={'stage':{'ID':1}};app.level=SimpleNamespace(get=lambda:'235');app.pets=[];app.placements={}
                app.combat_input=(1,'235',json.dumps([],sort_keys=True),[])
                app.sim_button=app.search_button=SimpleNamespace(configure=lambda **kw:None)
                received=[];loaded=[];app.guard=lambda fn:fn();app.load_simulation=lambda p:loaded.append(p)
                app.set_job_status=lambda value:received.append(value)
                write_json(app.combat_output,dict(status=state,reason='达到搜索时长上限',evaluation={'won':False}))
                app.poll_combat()
                self.assertEqual(bool(loaded),state=='no_solution')
                self.assertEqual(received[-1]['status'],state);self.assertIn('时长',received[-1]['reason'])

    @unittest.skipUnless(os.name=='nt','Windows autoplay lock')
    def test_initialization_error_writes_status_even_without_a_runner(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder);write_json(path/'geometry.json',{})
            with patch('sys.argv',['autoplay','--geometry',str(path/'geometry.json'),'--run-dir',str(path)]),\
                patch('autoplay.Runner',side_effect=LiveReadError('有效布阵对象不唯一')),\
                patch('msvcrt.locking'),patch('autoplay.RUNTIME',path):
                with self.assertRaises(LiveReadError):main()
            status=read_json(path/'status.json')
            self.assertEqual(status['event'],'stopped');self.assertEqual(status['reason_code'],'game_state_error')
            self.assertIn('对象不唯一',status['reason'])


if __name__=='__main__':unittest.main()
