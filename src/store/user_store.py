from __future__ import annotations
from sqlalchemy import Column, String, UniqueConstraint, JSON, Integer, ForeignKey, Boolean
from sqlalchemy.orm import relationship, validates
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # noinspection PyUnresolvedReferences
    from . import UserProfileStore
from . import Table

class UserStore(Table):
    __tablename__ = 'user'

    MAX_TOKEN_LEN = 512

    login_type = Column(String(32), nullable=False)
    login_identity = Column(String(128), nullable=False)
    login_properties = Column(JSON, nullable=False)

    enabled = Column(Boolean, nullable=False, default=True)
    group = Column(String(32), nullable=False)
    token = Column(String(MAX_TOKEN_LEN), nullable=True) # initialized in register logic

    auth_token = Column(String(128), nullable=False, unique=True)

    profile_id = Column(Integer, ForeignKey('user_profile.id'), nullable=True) # initialized in register logic
    profile = relationship('UserProfileStore', lazy='joined', foreign_keys=[profile_id])
    terms_agreed = Column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint('login_type', 'login_identity'),
    )

    def __repr__(self) -> str:
        nick = '(no profile)' if self.profile is None else self.profile.nickname_or_null
        return f'[#{self.id} {self.login_type}:{self.login_identity} {nick!r}]'

    @validates('login_properties')
    def validate_login_properties(self, _key: str, login_properties: Any) -> Any:
        assert isinstance(login_properties, dict), 'login_properties should be a dict'
        for k in login_properties.keys():
            assert isinstance(k, str), 'login_properties key should be string'

        return login_properties