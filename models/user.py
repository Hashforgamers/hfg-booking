from sqlalchemy import Column, Integer, String, Date, Sequence
from sqlalchemy.orm import relationship
from db.extensions import db

class User(db.Model):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    fid = Column(String(255), unique=True, nullable=False)
    avatar_path = Column(String(255), nullable=True)
    name = Column(String(255), nullable=False)
    gender = Column(String(50), nullable=True)
    dob = Column(Date, nullable=True)
    game_username = Column(String(255), unique=True, nullable=False)

    # Adding the parent_type column explicitly
    parent_type = Column(String(50), nullable=False, default='user')

    # Relationship to ContactInfo
    contact_info = relationship(
        'ContactInfo',
        primaryjoin="and_(foreign(ContactInfo.parent_id) == User.id, ContactInfo.parent_type == 'user')",
        back_populates='user',
        uselist=False,
        cascade="all, delete-orphan"
    )
