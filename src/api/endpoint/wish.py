from sanic import Blueprint, Request
from sanic_ext import validate
from dataclasses import dataclass
import time
from typing import Optional, Dict, Any

from ..wish import wish_endpoint
from ...state import User, ScoreBoard
from ...logic import Worker, glitter
from ...store import UserProfileStore

bp = Blueprint('endpoint', url_prefix='/wish')

def group_disp(g: str) -> str:
    return {
        'pku': '北京大学',
        'other': '校外选手',
        'staff': '工作人员',
        'banned': '已封禁',
    }.get(g, f'({g})')

@wish_endpoint(bp, '/game_info')
async def game_info(_req: Request, _worker: Worker, user: Optional[User]) -> Dict[str, Any]:
    return {
        'user': None if user is None else {
            'id': user._store.id,
            'group': user._store.group,
            'group_disp': group_disp(user._store.group),
            'token': user._store.token,
            'profile': {
                field: (
                    getattr(user._store.profile, f'{field}_or_null') or ''
                ) for field in UserProfileStore.PROFILE_FOR_GROUP.get(user._store.group, [])
            },
            'terms_agreed': user._store.terms_agreed,
        },
        'feature': {
            'push': True,
            'game': user is not None,
        },
    }

@dataclass
class UpdateProfileParam:
    profile: Dict[str, str]

@wish_endpoint(bp, '/update_profile')
@validate(json=UpdateProfileParam)
async def update_profile(_req: Request, body: UpdateProfileParam, worker: Worker, user: Optional[User]) -> Dict[str, Any]:
    if user is None:
        return {'error': 'NO_USER', 'error_msg': '未登录'}

    if 1000*time.time()-user._store.profile.timestamp_ms < 1000:
        return {'error': 'RATE_LIMIT', 'error_msg': '请求太频繁'}

    err = user.check_update_profile()
    if err is not None:
        return {'error': err[0], 'error_msg': err[1]}

    required_fields = user._store.profile.PROFILE_FOR_GROUP.get(user._store.group, [])
    fields = {}
    profile = UserProfileStore()
    for field in required_fields:
        if field not in body.profile:
            return {'error': 'INVALID_PARAM', 'error_msg': f'缺少 {field} 信息'}
        setattr(profile, f'{field}_or_null', str(body.profile[field]))
        fields[field] = str(body.profile[field])

    err = profile.check_profile(user._store.group)
    if err is not None:
        return {'error': 'INVALID_PARAM', 'error_msg': err}

    rep = await worker.perform_action(glitter.UpdateProfileReq(
        client=worker.process_name,
        uid=user._store.id,
        profile=fields,
    ))
    if rep.error_msg is not None:
        return {'error': 'REDUCER_ERROR', 'error_msg': rep.error_msg}

    return {}

@wish_endpoint(bp, '/agree_term')
async def agree_term(_req: Request, worker: Worker, user: Optional[User]) -> Dict[str, Any]:
    if user is None:
        return {'error': 'NO_USER', 'error_msg': '未登录'}

    if user._store.terms_agreed:
        return {}

    rep = await worker.perform_action(glitter.AgreeTermReq(
        client=worker.process_name,
        uid=user._store.id,
    ))
    if rep.error_msg is not None:
        return {'error': 'REDUCER_ERROR', 'error_msg': rep.error_msg}

    return {}

@wish_endpoint(bp, '/announcements')
async def announcements(_req: Request, worker: Worker) -> Dict[str, Any]:
    if worker.game is None:
        return {'error': 'NO_GAME', 'error_msg': '服务暂时不可用'}

    return {
        'list': [ann.describe_json() for ann in worker.game.announcements.list],
    }

@wish_endpoint(bp, '/triggers')
async def triggers(_req: Request, worker: Worker) -> Dict[str, Any]:
    if worker.game is None:
        return {'error': 'NO_GAME', 'error_msg': '服务暂时不可用'}

    return {
        'current': worker.game.cur_tick,
        'list': [{
            'timestamp_s': trigger.timestamp_s,
            'name': trigger.name,
            'status': 'prs' if trigger.tick==worker.game.cur_tick else 'ftr' if trigger.tick>worker.game.cur_tick else 'pst',
        } for trigger in worker.game.trigger._stores]
    }

CAT_COLORS = {
    'Misc': '#7e2d86',
    'Web': '#2d8664',
    'Binary': '#864a2d',
    'Algorithm': '#2f2d86',
}
FALLBACK_CAT_COLOR = '#000000'

def reorder_by_cat(values: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    for cat in CAT_COLORS.keys():
        if cat in values:
            out[cat] = None
    for k, v in values:
        out[k] = v
    return out

@wish_endpoint(bp, '/game')
async def get_game(_req: Request, worker: Worker, user: Optional[User]) -> Dict[str, Any]:
    if user is None:
        return {'error': 'NO_USER', 'error_msg': '未登录'}
    if worker.game is None:
        return {'error': 'NO_GAME', 'error_msg': '服务暂时不可用'}

    err = user.check_play_game()
    if err is not None:
        return {'error': err[0], 'error_msg': err[1]}

    policy = worker.game.policy.cur_policy
    active_board_key = 'score_pku' if user._store.group=='pku' else 'score_all'
    active_board_name = '北京大学' if user._store.group=='pku' else '总'
    active_board = worker.game.boards[active_board_key]
    assert isinstance(active_board, ScoreBoard)

    return {
        'challenge_list': None if not policy.can_view_problem else [{
            'id': ch._store.id,
            'title': ch._store.title,
            'category': ch._store.category,
            'category_color': CAT_COLORS.get(ch._store.category, FALLBACK_CAT_COLOR),

            'desc': ch.desc,
            'actions': ch._store.actions,
            'flags': [f.describe_json(user) for f in ch.flags],

            'tot_base_score': ch.tot_base_score,
            'tot_cur_score': ch.tot_cur_score,
            'passed_users_count': len(ch.passed_users),
            'status': 'passed' if user in ch.passed_users else 'partial' if user in ch.touched_users else  'untouched',
        } for ch in worker.game.challenges.list if ch.cur_effective],

        'user_info': {
            'tot_score_by_cat': [(k, v) for k, v in reorder_by_cat(user.tot_score_by_cat).items()] if user.tot_score_by_cat else None,
            'status_line': f'当前总分 {user.tot_score}，{active_board_name}排名 {active_board.uid_to_rank.get(user._store.id, "--")}',
        },

        'writeup_info': None if not policy.can_submit_writeup else {
            # todo
        },

        'last_announcement': worker.game.announcements.list[0].describe_json() if worker.game.announcements.list else None,
    }