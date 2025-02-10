from sqlalchemy import Column, Integer, String, Date, Sequence
from sqlalchemy.orm import relationship
from db.extensions import db

class User(db.Model):
    __tablename__ = 'users'
    
    id = Column(Integer, Sequence('user_id_seq', start=2000), primary_key=True)
    fid = Column(String(255), unique=True, nullable=False)
    avatar_path = Column(String(255), nullable=True)
    name = Column(String(255), nullable=False)
    gender = Column(String(50), nullable=True)
    dob = Column(Date, nullable=True)
    game_username = Column(String(255), unique=True, nullable=False)
