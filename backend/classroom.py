import os
import re
import secrets
import time
from dataclasses import dataclass, field

from fastapi import HTTPException
from sqlalchemy import func, select

from .db import ClassroomSeat, Training


@dataclass(frozen=True)
class Classroom:
    invite: str = field(repr=False)
    sessions: int
    turns: int
    turns_per_session: int

    @classmethod
    def from_env(cls):
        railway = bool(os.getenv('RAILWAY_PROJECT_ID'))
        if railway and 'SCAMSENSE_TRIAL_IPS' in os.environ and os.getenv('SCAMSENSE_ACCESS_MODE') != 'classroom':
            raise ValueError('该部署使用试用 IP 白名单；未经站主显式选择班级入口，不切换。')
        hosted = railway or os.getenv('RENDER') == 'true'
        mode = os.getenv('SCAMSENSE_ACCESS_MODE', 'classroom' if hosted else 'local')
        if mode == 'local' and not hosted and 'SCAMSENSE_CLASS_INVITE' not in os.environ:
            return None
        if mode != 'classroom':
            raise ValueError('班级服务须设置 SCAMSENSE_ACCESS_MODE=classroom。')
        invite = os.getenv('SCAMSENSE_CLASS_INVITE', '')
        if not re.fullmatch(r'[A-Za-z0-9_+/=-]{32,128}', invite):
            raise ValueError('请在服务端设置随机生成的 SCAMSENSE_CLASS_INVITE。')
        if any(secrets.compare_digest(invite.encode(), os.getenv(key, '').encode())
               for key in ('OPENAI_API_KEY', 'SCAMSENSE_DEEPSEEK_API_KEY')):
            raise ValueError('班级邀请与模型密钥必须分开设置。')

        def limit(key, default):
            value = os.getenv(key, str(default))
            if not re.fullmatch(r'[0-9]{1,8}', value):
                raise ValueError(f'{key} 必须为非负整数（最多 8 位）。')
            return int(value)

        return cls(invite, limit('SCAMSENSE_MAX_SESSIONS', 40), limit('SCAMSENSE_MAX_TURNS', 240),
                   limit('SCAMSENSE_TURNS_PER_SESSION', 20))

    def admit(self, authorization):
        if not secrets.compare_digest((authorization or '').encode(), f'Bearer {self.invite}'.encode()):
            raise HTTPException(403, '新建训练需要有效邀请。请用组织者发给你的完整班级邀请链接打开。')

    def add_seat(self, db, sid):
        if db.scalar(select(func.count()).select_from(ClassroomSeat)) >= self.sessions:
            raise HTTPException(429, '本班的新训练名额已用完。已有训练仍可从训练记录进入。')
        db.add(ClassroomSeat(sid=sid, attempts=0))

    def reserve_turn(self, db, sid):
        seat = db.get(ClassroomSeat, sid)
        if seat is None:
            raise HTTPException(403, '这不是受邀创建的班级训练。原记录可回看；新训练请使用班级邀请。')
        if seat.attempts >= self.turns_per_session:
            raise HTTPException(429, '本场的对话次数已用完。你仍可作出决定、结束训练和查看复盘。')
        if db.scalar(select(func.coalesce(func.sum(ClassroomSeat.attempts), 0))) >= self.turns:
            raise HTTPException(429, '全班的对话额度已用完。你仍可结束训练和查看复盘。')
        active = select(func.count()).select_from(Training).where(Training.locked_by.is_not(None), Training.lock_until > time.time())
        if db.scalar(active) >= 3:
            raise HTTPException(429, '已有三场对话正在回复，请稍后重试。本次未扣次数。')
        # A retry can cost money even when the previous attempt produced no saved message.
        seat.attempts += 1
